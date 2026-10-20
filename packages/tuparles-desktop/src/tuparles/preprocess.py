"""Audio conditioning before STT.

Whisper is robust to noise by design (trained on messy, real-world audio),
so we deliberately do NOT denoise: spectral subtraction / RNNoise add
artifacts, latency, and a dependency, and over-cleaning measurably hurts the
decode (the 2026-07-11 survey found original noisy audio beat enhanced audio
in 40/40 configs). Its VAD already drops silence *within* a decode.

Two things this module does own:

- **level** — `normalize_audio` / `prepare_pcm`: a soft take uses only a
  sliver of the int16 range, so the effective SNR after the /32768 scaling is
  poor. Peak normalization is the historical safe win (a no-op on already-loud
  audio, never clips) — but it is transient-blind: one keyboard clack pins the
  gain and quiet speech stays quiet (the 2026-07-15 quiet-take collapse). The
  `speech_leveler` setting (default on) swaps in the frame-wise compressor
  (`_compress_f32`) at the same seam. DC-offset removal fixes a biased mic
  either way. Before either, `far_field_gain` (#51) lifts a quiet room mic by
  one conservative linear gain. `prepare_pcm` is the single "prepare PCM for decode" seam every
  engine + the offline file path share, so conditioning can never silently
  diverge between rungs.
- **dead lead/tail** — `trim_silence`: the *whole-buffer* silence the in-decode
  VAD doesn't help with on the CPU rungs (qwen/whisper.cpp decode every silent
  second). Trimmed once at capture handoff, upstream of the engines. Speech is
  detected on a far-field-lifted copy (see `far_field_gain`) so trim and decode
  agree on what is speech; the slice returned is of the original audio.
"""

import logging

import numpy as np

from tuparles.config import (
    COMPRESS_FRAME_MS,
    COMPRESS_MAX_MAKEUP,
    COMPRESS_RATIO,
    COMPRESS_RELEASE_FRAMES,
    COMPRESS_THRESHOLD_DB,
    NORMALIZE_MAX_GAIN,
    NORMALIZE_SILENCE_FLOOR,
    NORMALIZE_TARGET_PEAK,
    SAMPLE_RATE,
    TRIM_MAX_REMOVED_FRAC,
    TRIM_MIN_RESULT_S,
    TRIM_PAD_LEAD_MS,
    TRIM_PAD_TAIL_MS,
    TRIM_RMS_FRAME_MS,
    TRIM_RMS_TOP_DB,
)

_log = logging.getLogger("tuparles.preprocess")

# --- far-field gain (#51) ----------------------------------------------------
# Every constant is a deliberate, conservative choice (see
# docs/research/2026-10-20-far-field-gain.md).
TARGET_SPEECH_DBFS = -26.0  # where lifted speech lands (typical near-field level)
MAX_GAIN_DB = 36.0  # hard cap: never turn a faint take into amplified hiss
FAR_FIELD_FRAME = SAMPLE_RATE // 50  # 20 ms analysis frames
FAR_FIELD_MIN_FRAMES = 25  # 0.5 s: too little audio to judge a level
FAR_FIELD_SILENCE_DBFS = -70.0  # speech level below this = digital silence
FAR_FIELD_MIN_SNR_DB = 8.0  # speech over the floor, else it is just noise
FAR_FIELD_QUIET_DBFS = -30.0  # at or above this the audio is not "quiet"
FAR_FIELD_PEAK_CEILING = 10.0 ** (-1.0 / 20.0)  # post-gain peak, -1 dBFS (0.891)
FAR_FIELD_MIN_GAIN_DB = 3.0  # a smaller lift is not worth touching the audio

# Last gain the stage applied (0.0 = no-op) — the forensics hook; the log line
# in prepare_pcm fires only when a lift happens.
last_far_field_gain_db = 0.0
_last_logged_gain = 0


def far_field_gain(
    pcm: np.ndarray, *, enabled: bool = True
) -> tuple[np.ndarray, float]:
    """Conservative automatic gain for quiet far-field mics (#51).

    Meeting-room / laptop-array audio measures ~-30 dBFS peak, -48 dBFS RMS and
    is only intelligible after ~+29 dB. On 20 ms frames, speech level = power
    mean of frames at or above the 70th percentile of frame RMS; floor = 10th
    percentile. A SINGLE linear gain (no compression, no clipping, no dynamics
    inside a take) lifts speech toward `TARGET_SPEECH_DBFS`, capped at
    `MAX_GAIN_DB` and at a -1 dBFS post-gain peak.

    Returns (pcm, gain_db); the input object untouched and 0.0 when it does
    nothing: disabled, under 0.5 s, digital silence, no clear speech over the
    floor (< 8 dB: amplifying noise is what makes decoders hallucinate), audio
    already at -30 dBFS or louder, or a lift under 3 dB. int16 in gives int16
    out, floating in gives the same floating dtype out. Pure, never mutates.
    """
    if not enabled or pcm.size < FAR_FIELD_MIN_FRAMES * FAR_FIELD_FRAME:
        return pcm, 0.0
    if pcm.dtype == np.int16:
        f = pcm.astype(np.float32) * np.float32(1.0 / 32768.0)
    else:
        f = pcm.astype(np.float32, copy=False)
    n = f.size // FAR_FIELD_FRAME
    frames = f[: n * FAR_FIELD_FRAME].reshape(n, FAR_FIELD_FRAME)
    power = np.maximum((frames.astype(np.float64) ** 2).mean(axis=1), 1e-12)
    db = 10.0 * np.log10(power)
    loud = db >= np.percentile(db, 70)
    speech_db = float(10.0 * np.log10(power[loud].mean()))
    noise_db = float(np.percentile(db, 10))
    if (
        not np.isfinite(speech_db)
        or speech_db < FAR_FIELD_SILENCE_DBFS
        or speech_db - noise_db < FAR_FIELD_MIN_SNR_DB
        or speech_db >= FAR_FIELD_QUIET_DBFS
    ):
        return pcm, 0.0
    peak = float(np.abs(f).max())
    if not np.isfinite(peak) or peak <= 0.0:
        return pcm, 0.0
    gain_db = min(max(TARGET_SPEECH_DBFS - speech_db, 0.0), MAX_GAIN_DB)
    gain_db = min(gain_db, 20.0 * float(np.log10(FAR_FIELD_PEAK_CEILING / peak)))
    if gain_db < FAR_FIELD_MIN_GAIN_DB:
        return pcm, 0.0
    lifted = f * np.float32(10.0 ** (gain_db / 20.0))
    if pcm.dtype == np.int16:
        out = np.clip(np.rint(lifted * 32768.0), -32768, 32767).astype(np.int16)
    else:
        out = lifted.astype(pcm.dtype, copy=False)
    return out, float(gain_db)


def normalize_audio(pcm: np.ndarray) -> np.ndarray:
    """float32 PCM in [-1, 1] → DC-removed, peak-normalized float32.

    Peak (not RMS) normalization so the gain can never push a sample past
    full scale — no clipping, ever. The gain is capped so a near-silent
    buffer isn't blown up into pure noise, and a silence floor leaves true
    silence untouched (amplifying it would only raise the hiss).
    """
    if pcm.size == 0:
        return pcm
    pcm = (pcm - np.float32(pcm.mean())).astype(np.float32)  # DC offset
    peak = float(np.abs(pcm).max())
    if peak < NORMALIZE_SILENCE_FLOOR:
        return pcm
    gain = min(NORMALIZE_TARGET_PEAK / peak, NORMALIZE_MAX_GAIN)
    return (pcm * np.float32(gain)).astype(np.float32)


def prepare_pcm(audio: np.ndarray) -> np.ndarray:
    """The single "prepare PCM for decode" seam every engine shares (#131).

    int16 mono → float32 [-1, 1], then level conditioning. float32 input (the
    offline ffmpeg path already delivers f32le in range) skips the /32768
    rescale and is conditioned directly. So the live daemon, whisper.cpp, qwen
    AND the offline file path condition audio identically — qwen used to bypass
    normalization entirely, the one silent divergence this closes. Trim is a
    SEPARATE upstream step (`trim_silence`, at capture handoff); this is
    decode-time only.

    Conditioning is `normalize_audio` (peak-driven) by default; the
    `speech_leveler` setting swaps in the transient-proof compressor
    (`_compress_f32`) — peak normalization is blind to a loud in-band transient
    (the push-to-talk clack pins the gain, quiet speech stays quiet; the
    2026-07-15 quiet-take lab), the compressor is not. One seam, so partials,
    finals and every engine flip together and can never silently diverge.
    """
    global last_far_field_gain_db, _last_logged_gain
    audio, gain_db = far_field_gain(audio, enabled=_far_field_gain_on())
    last_far_field_gain_db = gain_db
    if gain_db > 0.0 and round(gain_db) != _last_logged_gain:
        # Partials call this every tick: log only when the lift moves a whole dB.
        _last_logged_gain = round(gain_db)
        _log.info("far-field gain +%.1f dB", gain_db)
    pcm = audio if audio.dtype == np.float32 else audio.astype(np.float32) / 32768.0
    if _speech_leveler_on():
        f = (pcm - np.float32(pcm.mean())).astype(np.float32)  # DC offset
        try:
            return _compress_f32(f, SAMPLE_RATE)
        except Exception:
            pass  # conditioning must never cost a decode — fall back to peak
    return normalize_audio(pcm)


def _far_field_gain_on() -> bool:
    """Hot-read the `far_field_gain` setting (same pattern as the leveler)."""
    try:
        from tuparles import settings

        return bool(settings.get("far_field_gain"))
    except Exception:
        return False


def _speech_leveler_on() -> bool:
    """Hot-read the `speech_leveler` setting (like the trim toggle: applies to
    the next decode, no restart). Import inline + failure-safe so preprocess
    keeps zero hard deps beyond numpy/config for the engines that embed it."""
    try:
        from tuparles import settings

        return bool(settings.get("speech_leveler"))
    except Exception:
        return False


def to_int16(pcm: np.ndarray) -> np.ndarray:
    """Normalized float32 [-1, 1] → int16 PCM (the WAV the qwen C binary reads).
    Clipped so a stray out-of-range sample can't wrap around into loud garbage."""
    return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)


# --- speech compressor (the quiet-take rescue chain) -------------------------


def _compress_f32(f: np.ndarray, sample_rate: int) -> np.ndarray:
    """Frame-wise downward compressor + peak makeup on float32 [-1, 1].

    Why: peak normalization is transient-blind — one keyboard clack (the
    push-to-talk tap is in-band in every take) pins the peak-driven gain and
    quiet speech stays ~40 dB down, which collapses the batched final decode
    (2026-07-15 quiet-take lab: recall 0.16 on the worst consented take).
    Squashing everything above COMPRESS_THRESHOLD_DB by COMPRESS_RATIO first
    means the single peak makeup that follows reaches the *speech*, not the
    click. Dependency-free equivalent of the ffmpeg chain that won the lab A/B
    (acompressor threshold=-35dB:ratio=6:release=120ms + limiter → recall 0.98
    vs 0.58 unrescued, n=3 consented takes).
    """
    frame = max(1, int(sample_rate * COMPRESS_FRAME_MS / 1000))
    n_frames = -(-f.size // frame)  # ceil: the ragged tail is its own frame
    padded = np.zeros(n_frames * frame, dtype=np.float32)
    padded[: f.size] = f
    rms = np.sqrt((padded.reshape(n_frames, frame) ** 2).mean(axis=1))
    # Peak-hold envelope with a one-pole release (~120 ms): attack is instant at
    # frame granularity, decay is gradual so gain doesn't pump between syllables.
    release = float(np.exp(-1.0 / COMPRESS_RELEASE_FRAMES))
    env = np.empty(n_frames, dtype=np.float32)
    e = 0.0
    for i in range(n_frames):
        e = max(float(rms[i]), e * release)
        env[i] = e
    env_db = 20.0 * np.log10(np.maximum(env, 1e-9))
    # Above the threshold, keep 1/ratio of the overshoot (classic downward knee).
    over = np.maximum(env_db - COMPRESS_THRESHOLD_DB, 0.0)
    gain_db = -over * (1.0 - 1.0 / COMPRESS_RATIO)
    gain = np.repeat((10.0 ** (gain_db / 20.0)).astype(np.float32), frame)[: f.size]
    out = f * gain
    # Single peak makeup to target, capped so a near-silent take can't be blown
    # up into pure hiss; NORMALIZE_SILENCE_FLOOR leaves true silence untouched.
    peak = float(np.abs(out).max())
    if peak < NORMALIZE_SILENCE_FLOOR:
        return out
    makeup = min(NORMALIZE_TARGET_PEAK / peak, 10.0 ** (COMPRESS_MAX_MAKEUP / 20.0))
    return (out * np.float32(makeup)).astype(np.float32)


def compress_speech(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Transient-proof level conditioning for a whole take (see _compress_f32).

    int16 in → int16 out (float32 passes straight through as float32), so the
    daemon can hand the result to any engine exactly like the original buffer.
    Never raises — any failure returns the input unchanged (a failed rescue
    must not cost the take that triggered it)."""
    try:
        if pcm.size == 0:
            return pcm
        f = _to_float32(pcm)
        f = (f - np.float32(f.mean())).astype(np.float32)  # DC offset
        out = _compress_f32(f, sample_rate)
        if pcm.dtype == np.float32:
            return out
        return to_int16(out)
    except Exception:
        return pcm


# --- silence trim ----------------------------------------------------------

_silero_model = None  # lazily loaded ONNX VAD model, reused across takes
_silero_unavailable = False  # import/load failed once → RMS fallback from then on
_trim_warned = False  # trim NEVER raises; the first failure prints once, then quiet


def _to_float32(pcm: np.ndarray) -> np.ndarray:
    """int16 → float32 [-1, 1]; float32 passes through. For DETECTION only — the
    trimmed slice is taken from the original buffer, so its dtype is preserved."""
    if pcm.dtype == np.float32:
        return pcm
    return pcm.astype(np.float32) / 32768.0


def _silero_speech_span(
    audio_f: np.ndarray, sample_rate: int
) -> tuple[int, int] | None:
    """(first_speech_sample, last_speech_sample) via silero-vad's batch API, or
    None when silero ran and found NO speech. Raises when silero is unusable
    (not installed / load error) — the caller then drops to the RMS fallback.

    silero-vad is MIT, ONNX-CPU (no CUDA anywhere in this step), ~165× realtime
    on one core, and lives in the optional `trim` poetry group so the lean
    install never pays for it."""
    global _silero_model
    import silero_vad  # ImportError (or any load error) → caller falls back to RMS

    if _silero_model is None:
        _silero_model = silero_vad.load_silero_vad(onnx=True)
    ts = silero_vad.get_speech_timestamps(
        audio_f, _silero_model, sampling_rate=sample_rate
    )
    if not ts:
        return None  # silero is authoritative: no speech → don't second-guess it
    return int(ts[0]["start"]), int(ts[-1]["end"])


def _rms_speech_span(audio_f: np.ndarray, sample_rate: int) -> tuple[int, int] | None:
    """Deterministic energy trim (librosa `top_db` style), the dependency-free
    fallback when silero-vad isn't installed. Trailing silence after speech is
    the easy one-sided case; a per-frame RMS gate relative to the loudest frame
    finds the first and last voiced frame honestly. None = whole buffer silent."""
    peak = float(np.abs(audio_f).max())
    if peak < NORMALIZE_SILENCE_FLOOR:
        return None
    frame = max(1, int(sample_rate * TRIM_RMS_FRAME_MS / 1000))
    n_frames = audio_f.size // frame
    if n_frames == 0:
        return None
    frames = audio_f[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    ref = float(rms.max())
    if ref <= 0.0:
        return None
    thresh = ref * (10.0 ** (-TRIM_RMS_TOP_DB / 20.0))
    voiced = np.nonzero(rms >= thresh)[0]
    if voiced.size == 0:
        return None
    start = int(voiced[0]) * frame
    end = min(audio_f.size, (int(voiced[-1]) + 1) * frame)
    return start, end


def trim_silence(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Trim leading + trailing silence off a mono take (int16 or float32) before
    decode. Returns a slice of the ORIGINAL buffer (dtype preserved, never
    amplified). Speech is DETECTED on a `far_field_gain`-lifted float copy
    (when the setting is on), so the trim sees the same speech the decode will:
    the later `prepare_pcm` lift applies to the trimmed slice.

    Three-tier, GPU-or-CPU by construction: (a) silero-vad batch API on the ONNX
    CPU runtime when importable; (b) a deterministic RMS lead/tail cut, no new
    dep; (c) the buffer unchanged. Never raises — any failure prints once and
    returns the input.

    Conservative by the house bias — a wrong trim is worse than a slow decode:
    - lead/tail ONLY; interior pauses are never touched (MVP);
    - keeps `TRIM_PAD_LEAD_MS` / `TRIM_PAD_TAIL_MS` margins around speech;
    - bails to the untrimmed buffer if the result would be under
      `TRIM_MIN_RESULT_S`, or if the trim would remove more than
      `TRIM_MAX_REMOVED_FRAC` of the take (a VAD misfire on soft speech must
      never hand an engine near-nothing).
    """
    global _silero_unavailable, _trim_warned
    if pcm.size == 0:
        return pcm
    n = pcm.size
    try:
        # Detect on the far-field-LIFTED copy so trim and decode agree on what
        # counts as speech (a -48 dBFS take trims like the same take 29 dB
        # louder; a faint take is not judged "silent" by an absolute floor).
        # `pcm` itself is never modified: we slice and return the original.
        audio_f, _ = far_field_gain(_to_float32(pcm), enabled=_far_field_gain_on())
        if not _silero_unavailable:
            try:
                span = _silero_speech_span(audio_f, sample_rate)
            except Exception:
                # silero missing or broken (no onnxruntime, bad load…): switch to
                # the RMS fallback permanently so we don't thrash a failing import
                # on every take, and use its result now.
                _silero_unavailable = True
                span = _rms_speech_span(audio_f, sample_rate)
        else:
            span = _rms_speech_span(audio_f, sample_rate)
        if span is None:
            return pcm  # no speech detected (tier c) — hand the engine the buffer
        start, end = span
        lead = int(sample_rate * TRIM_PAD_LEAD_MS / 1000)
        tail = int(sample_rate * TRIM_PAD_TAIL_MS / 1000)
        start = max(0, start - lead)
        end = min(n, end + tail)
        if end <= start:
            return pcm
        trimmed = pcm[start:end]
        if trimmed.size < int(sample_rate * TRIM_MIN_RESULT_S):
            return pcm  # too short — keep the original (soft-speech safety)
        if trimmed.size < n * (1.0 - TRIM_MAX_REMOVED_FRAC):
            return pcm  # >95% removed — distrust it, keep the original
        return trimmed
    except Exception as exc:  # trim MUST never break a take
        if not _trim_warned:
            print(f"silence trim failed ({str(exc)[:120]}); using untrimmed audio")
            _trim_warned = True
        return pcm
