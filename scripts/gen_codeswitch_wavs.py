#!/usr/bin/env python3
"""Render the adversarial code-switch corpus to WAV, multi-engine.

Why multi-engine: a single voice proves little. We render every case through
several voices so a pass means "survives diverse acoustics", not "survives one
TTS quirk". The deliberately useful trick is cross-lingual voicing — a *French*
voice reading the English tokens produces authentic franglais phonemes, which
is exactly the acoustic that trips Whisper (see the seed case fanout→fais-un-air).

Engines:
  * piper  — local neural TTS (CPU), realistic prosody. Voices auto-download.
  * espeak — formant synth, robotic but deterministic and instant; a different
             failure surface than neural, so a useful second opinion.

Every output is normalised through ffmpeg to 16 kHz mono s16le, so the harness
loads it with stdlib `wave` into exactly the int16 array the engine expects —
the same shape the microphone path produces. Idempotent: existing WAVs are
skipped unless --force. Writes a manifest the pytest harness reads.

Run (no GPU needed — this is pure CPU synthesis):
    poetry run python scripts/gen_codeswitch_wavs.py
    poetry run python scripts/gen_codeswitch_wavs.py --force --engines piper
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "tests" / "data" / "codeswitch" / "corpus.json"
DEFAULT_OUT = REPO_ROOT / "tests" / "data" / "codeswitch" / "wav"
DEFAULT_VOICES = REPO_ROOT / "tests" / "data" / "codeswitch" / "voices"

# A French voice and an English voice per engine: the cross-lingual pair is the
# point (FR voice on English tokens = the realistic trap).
PIPER_VOICES = {
    "piper-fr": "fr_FR-siwis-medium",
    "piper-en": "en_US-amy-medium",
}
PIPER_VOICE_PATHS = {  # HF rhasspy/piper-voices repo-relative stems
    "fr_FR-siwis-medium": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium",
    "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium",
}
PIPER_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

ESPEAK_VOICES = {
    "espeak-fr": "fr",
    "espeak-en": "en-us",
}

TARGET_RATE = 16_000


def log(msg: str) -> None:
    print(msg, flush=True)


def _ffmpeg_normalise(src: Path, dst: Path) -> bool:
    """src (any WAV) → dst (16 kHz mono s16le). True on success."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-ar", str(TARGET_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        log(f"    ffmpeg failed: {proc.stderr.strip()[:200]}")
        return False
    return True


# --- piper ------------------------------------------------------------------

def _piper_available() -> bool:
    return shutil.which("piper") is not None


def _ensure_piper_voice(voice: str, voices_dir: Path) -> Path | None:
    """Return the .onnx path, downloading the voice (+config) if missing."""
    onnx = voices_dir / f"{voice}.onnx"
    cfg = voices_dir / f"{voice}.onnx.json"
    stem = PIPER_VOICE_PATHS.get(voice)
    if stem is None:
        log(f"    unknown piper voice {voice}")
        return None
    voices_dir.mkdir(parents=True, exist_ok=True)
    for path, url in ((onnx, PIPER_HF_BASE + stem + ".onnx"),
                      (cfg, PIPER_HF_BASE + stem + ".onnx.json")):
        if path.exists() and path.stat().st_size > 0:
            continue
        log(f"    downloading {path.name} …")
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as exc:  # noqa: BLE001 - any net error → skip voice
            log(f"    download failed ({str(exc)[:120]}); skipping voice")
            return None
    return onnx


def _piper_synth(text: str, onnx: Path, dst: Path) -> bool:
    proc = subprocess.run(
        ["piper", "--model", str(onnx), "--output_file", str(dst)],
        input=text, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        log(f"    piper failed: {proc.stderr.strip()[:200]}")
        return False
    return True


# --- espeak -----------------------------------------------------------------

def _espeak_bin() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def _espeak_synth(text: str, voice: str, dst: Path, espeak: str) -> bool:
    proc = subprocess.run(
        [espeak, "-v", voice, "-s", "160", "-w", str(dst), text],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        log(f"    espeak failed: {proc.stderr.strip()[:200]}")
        return False
    return True


# --- driver -----------------------------------------------------------------

def resolve_voices(engines: set[str], voices_dir: Path) -> dict:
    """Build {voice_label: synth_callable(text, dst)->bool} for what's available."""
    voices: dict = {}

    if "piper" in engines:
        if _piper_available():
            for label, voice in PIPER_VOICES.items():
                onnx = _ensure_piper_voice(voice, voices_dir)
                if onnx is not None:
                    voices[label] = lambda text, dst, o=onnx: _piper_synth(text, o, dst)
        else:
            log("piper not found — `poetry run pip install piper-tts` to enable it. "
                "Skipping piper voices.")

    if "espeak" in engines:
        espeak = _espeak_bin()
        if espeak:
            for label, voice in ESPEAK_VOICES.items():
                voices[label] = lambda text, dst, v=voice: _espeak_synth(text, v, dst, espeak)
        else:
            log("espeak not found — `sudo apt-get install -y espeak-ng` to enable it. "
                "Skipping espeak voices.")

    return voices


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES)
    ap.add_argument("--engines", default="piper,espeak",
                    help="comma list: piper,espeak")
    ap.add_argument("--force", action="store_true",
                    help="regenerate WAVs that already exist")
    args = ap.parse_args()

    engines = {e.strip() for e in args.engines.split(",") if e.strip()}
    corpus = json.loads(args.corpus.read_text())
    cases = corpus["cases"]
    args.out.mkdir(parents=True, exist_ok=True)

    voices = resolve_voices(engines, args.voices_dir)
    if not voices:
        log("No TTS engine available — nothing to generate.")
        return 1
    log(f"Voices: {', '.join(sorted(voices))}  |  {len(cases)} cases")

    made = skipped = failed = 0
    for case in cases:
        cid = case["id"]
        text = case["text"]
        for label, synth in voices.items():
            dst = args.out / f"{cid}__{label}.wav"
            if dst.exists() and not args.force:
                skipped += 1
                continue
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                if synth(text, Path(tmp.name)) and _ffmpeg_normalise(Path(tmp.name), dst):
                    made += 1
                    log(f"  ✓ {dst.name}")
                else:
                    failed += 1
                    log(f"  ✗ {dst.name}")

    # Build the manifest from what's actually on disk, not just this run's
    # voices — so regenerating one engine never silently drops another's WAVs.
    manifest = scan_manifest(args.out, {c["id"] for c in cases})
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(
        {"corpus_version": corpus.get("version"), "files": manifest}, indent=2,
    ) + "\n")
    log(f"\nmade={made} skipped={skipped} failed={failed} "
        f"→ {len(manifest)} WAVs in manifest ({manifest_path})")
    return 0 if manifest else 1


def scan_manifest(out_dir: Path, known_ids: set[str]) -> list[dict]:
    """Every `{case_id}__{voice}.wav` on disk whose case_id is in the corpus.

    Parsed from filenames so the manifest reflects reality regardless of which
    engines were run; unknown/stale ids are skipped (a renamed corpus entry
    shouldn't smuggle orphaned audio back in).
    """
    files = []
    for wav in sorted(out_dir.glob("*__*.wav")):
        cid, _, label = wav.stem.rpartition("__")
        if cid not in known_ids:
            continue
        files.append({
            "file": wav.name, "case_id": cid,
            "voice": label, "engine": label.split("-")[0],
        })
    return files


if __name__ == "__main__":
    sys.exit(main())
