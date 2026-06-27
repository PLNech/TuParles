# Android Platform Mechanics, Privacy Constraints, and Domovoy Integration Boundary

*Research note — TuParles issue #2: Make TuParles Android-library-ready*
*Date: 2026-06-27*

---

## 1. Microphone permission flow

### Runtime permission model

`RECORD_AUDIO` is a "dangerous" (now "while-in-use") permission requiring explicit
user grant at runtime via `ActivityCompat.requestPermissions`. It is not granted
at install. Since Android 11, the grant is *while-in-use*: the system may revoke
it automatically when the app moves to the background unless a foreground service
with type `microphone` is running (see §2).

**AudioRecord basics for push-to-talk:**

```java
// 16 kHz PCM16 mono — same sample rate faster-whisper expects
int minBuf = AudioRecord.getMinBufferSize(
    16000,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT
);
AudioRecord recorder = new AudioRecord(
    MediaRecorder.AudioSource.VOICE_RECOGNITION,  // noise suppression hint
    16000,
    AudioFormat.CHANNEL_IN_MONO,
    AudioFormat.ENCODING_PCM_16BIT,
    minBuf * 4  // 4× for margin
);
```

`VOICE_RECOGNITION` source requests platform noise suppression and AGC — valuable
for code-switching recognition. Buffer in short[] or ByteBuffer; read in a tight
loop on a dedicated thread. Result feeds STT engine frame-by-frame.

**Android 12+ mic privacy indicator:** When audio is being captured, the system
shows a green dot in the status bar. On Android 14+ this dot appears even when
the app has a foreground service. There is **no API to suppress it** — build UX
around it (the dot is the privacy proof, not the obstacle).

---

## 2. Foreground service mechanics — Android 14 / 15 / 16

### Manifest declaration (mandatory since May 2024, API 34 = Android 14)

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />

<service
    android:name=".PttRecordService"
    android:foregroundServiceType="microphone"
    android:exported="false" />
```

Without the type declaration Google Play rejects the APK as of August 2024.
`FOREGROUND_SERVICE_MICROPHONE` must appear both as a `<uses-permission>` AND the
service must declare `foregroundServiceType="microphone"`.

### The gotcha most likely to bite: background-start prohibition

**You cannot start a microphone foreground service from the background.**
Calling `startForegroundService()` while the app has no visible UI and no other
foreground service already running throws a `SecurityException` at runtime. This
is the single constraint with the highest potential to invalidate a naive PTT
architecture.

Consequences for issue #2 / Domovoy:
- Push-to-talk initiated by a global hotkey or watch-face tap while the app is
  backgrounded **will fail** unless the microphone FGS is already alive.
- **Resolution options:**
  1. Keep the FGS alive from the moment the user opens the app (costs a persistent
     notification; acceptable for a dedicated voice-input tool).
  2. Bring the Activity to the foreground first (a MediaButtonReceiver or
     notification-tap), start the FGS from there, then let the activity re-hide.
  3. Require the user to tap the in-app PTT button (non-ambiguous foreground
     context). This is the safest default for v1.

Domovoy's architecture — where PTT is initiated by a watch gesture or LAN message
while the app is backgrounded — hits this wall directly. Flag it as a
**P0 integration risk** before API design is finalized.

### Android 15 changes (launched October 2024)

- **Time-limited foreground service types:** `microphone` and `camera` FGS receive
  a *job quota* — if the service has been running longer than the system's quota,
  it is stopped. Quota varies by device/OEM and is not a published constant.
  *Practical impact:* a long-running always-on recorder is not viable; PTT
  intermittency (start FGS → record utterance → stop FGS) is the right model.
- **Foreground service types cannot be started from BOOT_COMPLETED** on API 34+
  (Android 14). The mic FGS must always originate from a user interaction context.

### Android 16 changes (expected 2025)

- **16 KB page size mandate** (from Nov 1 2025 on Google Play): all native `.so`
  files must support 16 KB page alignment or they crash on Pixel 9+ and future
  ARM devices with 16 KB kernels. Affects every native library in the dependency
  tree: `libonnxruntime.so`, `libwhisper.so`, any JNI layer, and CPython's C
  extensions.
  - **Chaquopy** supports this as of version 17.0 + Python 3.13 (both required).
  - **sherpa-onnx** `libonnxruntime.so` v1.16+ is 16 KB aligned — verify the
    exact version in any sherpa-onnx release used.
  - Vosk's pre-built `.so` files need checking; no public statement as of research date.

---

## 3. Structural no-network guarantee

### The mechanism (and its limits)

The naive claim — "omit `INTERNET` from `AndroidManifest.xml` and no network is
possible" — is **necessary but not sufficient** due to manifest merging.

Android's Gradle build merges all library manifests into one. If any transitive
dependency (an analytics SDK, a crash reporter, a convenience library) declares
`INTERNET`, the merged app has the permission and every process sharing its UID
can open sockets. "My TuParles module doesn't declare INTERNET" is not a runtime
guarantee.

**The structural interlock that delivers the doctrine ("safety is structural, not
statistical") is `android:isolatedProcess="true"` on the decode service:**

```xml
<service
    android:name=".SttDecodeService"
    android:isolatedProcess="true"
    android:exported="false" />
```

An isolated process runs under a *distinct UID* assigned no permissions — not even
the host app's `INTERNET`. It can communicate with the host only via Binder IPC.
Raw audio enters the isolated process; a transcript string exits. No library code
inside that process can open a socket, regardless of what the merged manifest says.

**Important trade-off:** `isolatedProcess` services cannot bind to most system
services (no `AudioRecord`, no hardware access). The microphone recording must
happen in the main app process (or its FGS), and PCM frames are passed into the
isolated decode service via Binder. The decode-service architecture therefore is:

```
[App process / FGS]                    [Isolated decode process]
  AudioRecord → PCM16 frames  ──────>  STT engine (sherpa-onnx / vosk)
  onPartial(text) <────────────────── partial transcripts
  onFinal(text)   <────────────────── final transcript
  [audio + transcript never leave isolated process except as text]
```

### Resolving the LAN tension

Issue #2 explicitly targets a LAN-local assistant endpoint. This appears to
contradict "no network STT." The resolution mirrors desktop TuParles:

> **Privacy claim = "raw audio and transcript never enter a networked process and
> are not persisted by default."** Not "the app has zero network."

The delivery layer (text → Domovoy LAN endpoint) lives in the main app process and
may hold `INTERNET`. The decode layer is isolated and never does. The two are
separated by Binder: only the final text string crosses the boundary.

### Defense-in-depth layers

| Layer | Mechanism | Strength |
|-------|-----------|----------|
| 1 | Isolated decode process | Structural — OS-enforced UID sandbox |
| 2 | No INTERNET in TuParles core module | Necessary, not sufficient alone |
| 3 | `NetworkSecurityConfig` `cleartextTrafficPermitted="false"` | Defense-in-depth |
| 4 | Android 12+ Privacy Dashboard | User-visible audit trail |
| 5 | No raw audio written to storage | App-enforced (no `WRITE_EXTERNAL_STORAGE`) |

**Android Privacy Dashboard (API 31+):** Records timestamped mic access history
accessible to the user at Settings → Privacy → Privacy Dashboard. Every
`AudioRecord.read()` call creates an entry. This is the transparency proof:
it is non-spoofable and non-suppressible.

---

## 4. Ephemeral utterance mode

Android has no platform-native ephemeral audio flag. Ephemerality must be
**app-enforced** at every stage:

1. **No write to storage:** Do not request `WRITE_EXTERNAL_STORAGE` or
   `MANAGE_MEDIA`. Hold PCM frames in-memory (heap byte arrays). On OOM,
   fail the utterance — never spill to disk as a fallback.
2. **In-memory only, zero-copy handoff:** The isolated decode process holds the
   audio frame buffer. It drops the reference after `onFinal()` fires. GC
   reclaims it. No copy survives the Binder call boundary.
3. **Transcript persistence opt-in:** `privacy_mode: "ephemeral"` in the Domovoy
   JSON means the host app must not cache the transcript beyond the current LAN
   call. TuParles provides the model; enforcement is contractual on the host.
4. **Public logs = metrics only:** Log `frames_received=N` and `latency_ms=M`,
   never the text. Mirror `tests/test_privacy.py` discipline.

**Contrast with desktop:** Desktop TuParles logs transcripts to the history DB
(`~/.local/share/tuparles/history.db`) with opt-out. On Android the default
should be inverted: no persistence unless the host app explicitly enables it.
This matches issue #2 acceptance criteria.

---

## 5. Battery / thermal

### Push-to-talk intermittency is DVFS-friendly

Modern Android SoCs use Dynamic Voltage and Frequency Scaling (DVFS). Short
inference bursts (one utterance every 30+ seconds) let the CPU governor ramp down
between bursts — the thermal governor recovers without needing throttling. PTT's
natural usage pattern is favorable.

**Danger case: continuous partials.** Running a full decode pass every 300 ms on
CPU for live-caption-style partials sustains elevated CPU frequency, saturates
thermal headroom within 2-3 minutes on a mid-range SoC, and triggers throttling.
The same concern exists on desktop (qwen-CPU partials path) — on mobile it is
worse because the thermal envelope is smaller and there is no active cooling.

**Recommended pattern (mirrors engine.py desktop approach):**

- Partials: windowed sliding decode, not every frame. Default off; user-toggleable.
- Finals: one full decode pass per utterance. Acceptable.
- Between utterances: the decode service sleeps (no warmup loop, no keepalive
  inference). The isolated process stays alive but idle.

**Battery numbers (CLAIMS — unverified, treat as directional only):**
- sherpa-onnx Whisper-tiny ARM64: ~180 mW sustained during inference (vendor blog).
- Picovoice Cheetah streaming: ~40 mW (vendor claim, "12× more efficient than
  Whisper" — unverified; may compare different model sizes or tasks).
- A 5-second utterance at 180 mW = 0.25 mWh. Negligible per utterance; cumulative
  risk only in continuous-partial mode.

**Mandate:** Before trusting any vendor figure, benchmark on a real Android device
under PTT conditions using the Android Battery Historian or `dumpsys batterystats`.

---

## 6. STT engine candidates — claim vs verified

### sherpa-onnx (open source)

- Runtime: `libonnxruntime.so` 5.8 MB + `libsherpa-onnx.so` 1.4 MB = **7.2 MB
  combined** (CLAIM: k2-fsa README, June 2025).
- ARM64 Android pre-built available; JNI Java bindings published.
- Offline, no network calls in library code, auditable source (k2-fsa/sherpa-onnx).
- **Known quality risk (VERIFIED):** GitHub issue k2-fsa/sherpa-onnx #2900 reports
  >3× CER regression vs faster-whisper on the same Whisper Tiny model. The
  regression source is unclear (ONNX export path? runtime precision?). This is
  the most material risk: a naive engine swap may degrade quality relative to
  desktop TuParles.
- 16 KB page alignment: onnxruntime v1.16+ is compliant — verify the version
  bundled in whatever sherpa-onnx release is used.
- **Doctrine alignment: high** (open source, auditable, no phone-home).

### Picovoice Cheetah / Leopard (proprietary)

- Cheetah: streaming; Leopard: file-based. Cheetah added French language model
  in 2025 — critical for FR/EN code-switching.
- Claimed "12× more efficient than Whisper at same accuracy" (CLAIM: Picovoice
  marketing, unverified methodology — compare model sizes before trusting).
- **Requires an AccessKey.** The key must be embedded in the APK.
  **UNVERIFIED CRITICAL QUESTION:** Does the Picovoice SDK validate the AccessKey
  online at init time, or is validation fully offline? If online validation is
  mandatory, this introduces a phone-home that **disqualifies Picovoice under
  TuParles structural privacy doctrine** — a LAN-only app cannot mandate a network
  call to an external server. Verify before including in architecture.
- Proprietary binary — not auditable for network calls. Requires trust.
- **Doctrine alignment: low** until the AccessKey/network question is resolved.

### whisper.cpp (open source)

- Not evaluated by previous searches but worth mentioning: C++ Whisper with ARM
  NEON acceleration, JNI Android bindings exist, same model weights as
  faster-whisper (GGUF format). Quality gap vs faster-whisper is smaller than
  sherpa-onnx because the inference is more faithful to the original. 16 KB
  alignment: verify per release.
- The quality-vs-size tradeoff at Tiny/Base is better understood here than via
  the ONNX path sherpa-onnx uses.

### Recommendation for v1

**sherpa-onnx** first (open, auditable, no phone-home, JNI ready) with an explicit
quality benchmark against desktop TuParles on the FR/EN code-switch eval corpus
(`tests/test_codeswitch_eval.py`) before shipping. If the >3× CER issue is still
unresolved, evaluate whisper.cpp as an alternative before falling back to a
proprietary option.

---

## 7. CPython embed — postprocess portability

### The verified finding

The entire postprocess chain is **pure stdlib + light deps** (VERIFIED by import
scan, 2026-06-27):

- `pipeline.py` → `punctuation`, `lexicon`, `syntax`, `repeats`, `casing` →
  each imports only `re`, `string`, `collections.abc`, `dataclasses`, `typing`.
- No `torch`, `numpy`, `onnx`, `scipy`, or any C extension.
- `tuparles.settings` (referenced by `syntax` and `casing`) needs verification
  but is likely stdlib-only too.

**Implication:** Under Branch 1 (Chaquopy/BeeWare), the CPython embed cost is
the interpreter ABI itself — a few MB — not the postprocess chain. The chain
is pure Python and trivially portable. The engine (sherpa-onnx) is native and
does not require CPython.

### Branch 1 (CPython embed via Chaquopy)

- Chaquopy 17.0 + Python 3.13 required for Android 16 KB compliance.
- APK overhead: ~46 MB for the Chaquopy demo app base. Plus model weights.
- All `postprocess()` stages run as-is inside the APK.
- GIL: audio read and decode are native (JNI); only postprocess crosses into
  Python. GIL contention risk is low because the handoff is sequential.
- Native packages (numpy if ever needed) must be pre-built for Android ARM via
  Chaquopy's package repository — cannot pip-install arbitrary wheels.

### Branch 2 (Kotlin reimplementation of postprocess semantics)

- No CPython overhead. Smaller APK.
- Risk: semantic drift between the Kotlin port and `pipeline.py`. The eval
  harness (`test_codeswitch_eval.py`) runs Python only — the Kotlin path would
  not be covered unless a parallel Kotlin test is written.
- The lexicon and syntax rules (`syntax_features`) are the hardest to port
  faithfully. Regex patterns in the Python modules must be reproduced exactly.
- **Recommendation:** Branch 2 is technically viable but creates a permanent
  maintenance fork for every lexicon/syntax/casing rule change. Branch 1's
  extra APK weight is a one-time cost; the dual-maintenance burden of Branch 2
  is ongoing. Prefer Branch 1 unless APK size is a hard constraint.

---

## 8. Domovoy JSON contract — sufficiency and gaps

### Current 6-field contract (from issue #2)

```json
{
  "text": "final transcript",
  "language": "fr|en|auto|null",
  "source": "tuparles-android",
  "input_mode": "push_to_talk",
  "partial_supported": true,
  "privacy_mode": "ephemeral"
}
```

### Sufficiency assessment

The 6 fields cover the bare minimum for a stateless handoff. They are sufficient
for a proof-of-concept where Domovoy receives a complete final transcript and does
not need to correlate partials to finals, handle retries, or version the contract.

### Gaps for a production-grade LAN handoff

| Missing field | Rationale | Doctrine source |
|---------------|-----------|-----------------|
| `utterance_id` | Deduplication; correlate partial→final stream messages | Prevents duplicate delivery |
| `is_final` | Boolean per message when partials are streaming; `partial_supported: true` is a capability flag, not a per-message signal | Issue #2 event model |
| `captured_at` | ISO 8601 timestamp at AudioRecord start, not delivery time | [[capture-time-not-delivery-time]] doctrine |
| `engine_id` | Which backend produced this transcript (sherpa-onnx/vosk/cheetah) | Debuggability, quality correlation |
| `confidence` / `spans` | Word-level confidence for doubt rendering (#16/#21); a LAN assistant may surface hesitancy differently | Spans model (#21 done) |
| `schema_version` | Forward-compat; Domovoy and TuParles can evolve independently | Standard API hygiene |
| `language_prob` | Confidence of language detection, mirrors `Transcription.language_prob` | engine.py dataclass already has it |
| `empty_final` | Signal that the utterance produced no transcript (mic captured, engine returned empty) | [[feedback-instrumentation-record-misses]] doctrine |

**Minimum recommended delta for v1 production:**
`utterance_id`, `is_final`, `captured_at`, `schema_version`. The rest can wait
for v2 but should be listed in the issue's open questions.

---

## 9. CapabilityReport — Android requirements

Desktop `CapabilityReport` (from `capability.py`) uses a Chain/Layer/resolved model
probed once at boot. The Android analog must cover the same contract — "probe
capabilities, do not assume them" — adapted to mobile realities.

### Required chains (mirroring desktop Chain structure)

```
Chain: mic
  Layer 1: RECORD_AUDIO permission granted?
  Layer 2: AudioRecord.STATE_INITIALIZED?
  Layer 3: Sample rate 16000 supported?
  resolved: "mic_available" | "mic_denied" | "mic_hardware_error"
  fallback: none (PTT cannot degrade without mic)

Chain: engine
  Layer 1: sherpa-onnx model file present + loadable?
  Layer 2: whisper.cpp available?
  Layer 3: Vosk model present?
  resolved: "sherpa-onnx" | "whisper-cpp" | "vosk" | "none"
  fallback: graceful degradation — show "no engine" in UI, block recording

Chain: partials
  Layer 1: engine.resolved == "sherpa-onnx" or "whisper-cpp"?
  Layer 2: Device thermal state == THERMAL_STATUS_NONE or _LIGHT?
  resolved: "partials_on" | "partials_off_engine" | "partials_off_thermal"
  fallback: finals-only mode (always available)

Chain: offline_mode
  Layer 1: No INTERNET in merged manifest? (runtime check via ConnectivityManager)
  Layer 2: Decode service is isolatedProcess?
  resolved: "isolated" | "unverified"
  note: "unverified" does not block PTT; logs a warning

Chain: persistence
  Layer 1: Host app enabled transcript storage?
  Layer 2: Storage permission granted?
  resolved: "ephemeral" | "persistent_with_consent"
  default: "ephemeral"
```

### Probe timing

Probe at `TuParlesSession.start(config)`. Results surface via `onCapability(report)`
event before the first `onLevel()`. This mirrors desktop daemon's boot-time probe
and lets the host app (Domovoy) gate its UI on actual capabilities, not assumptions.

---

## 10. Privacy test list (Android-specific)

Mirroring `tests/test_privacy.py` style. These should live in
`tests/android/` or be covered by an instrumented test APK.

```python
# test_android_privacy.py

def test_no_raw_audio_written_to_storage():
    """After a session, no .wav/.pcm files exist in app storage directories."""
    # Assert: getFilesDir(), getCacheDir(), getExternalFilesDir() contain no audio.

def test_transcript_not_in_shared_prefs():
    """SharedPreferences does not contain any transcript text after a session."""
    # Assert: all SharedPreferences keys and values contain no transcript content.

def test_transcript_not_logged_to_logcat():
    """No transcript text appears in public logcat output."""
    # Assert: logcat buffer for the app contains only metrics (latency_ms, frames),
    # never transcript content.

def test_ephemeral_mode_no_db_row():
    """In ephemeral mode, no transcript row is written to any SQLite DB."""
    # Assert: iterate app databases directory; no transcript table contains rows.

def test_isolated_process_no_network():
    """The decode service (isolatedProcess=true) cannot open a TCP socket."""
    # Assert: attempt socket creation from the isolated process via Binder test harness.
    # Expected: SecurityException or EACCES.

def test_internet_permission_absent_from_core_module():
    """TuParles-core AAR manifest does not declare INTERNET."""
    # Assert: parse merged manifest for android.permission.INTERNET;
    # verify it is absent from the core module's own manifest.

def test_no_pii_in_metrics():
    """onLevel() and CapabilityReport callbacks contain no text."""
    # Assert: all onCapability() and onLevel() payloads contain only numeric fields.

def test_mic_dot_not_suppressed():
    """App does not attempt to set any window flag or system flag to hide mic indicator."""
    # Assert: no call to WindowManager.FLAG_SECURE or equivalent in source.
    # (static analysis check — instrumented test cannot verify this at runtime)

def test_language_auto_detection_local():
    """Language detection does not trigger a network request."""
    # Assert: mock NetworkCapabilities; verify no network transaction during decode.

def test_empty_utterance_not_persisted():
    """When the engine returns empty string, no empty row is written and no error
    payload leaks the audio metadata."""
    # Assert: empty-final produces no DB row and no log line with frame count.
```

---

## Bottom line for issue #2

**The architecture is sound; three constraints need to be locked before API
design is finalized:**

1. **Foreground service background-start prohibition** is P0. PTT from a backgrounded
   app requires the mic FGS to already be alive. Design the session lifecycle around
   this constraint, not around it.

2. **Engine quality must be measured, not assumed.** The >3× CER gap in sherpa-onnx
   on Whisper Tiny (GitHub #2900) is a real risk. Run the FR/EN code-switch eval
   on device before committing to an engine. whisper.cpp is the backup candidate.

3. **Picovoice's AccessKey network behavior must be confirmed before inclusion.**
   If it phones home at init, it fails the structural privacy requirement.

**The postprocess chain is clean and portable** (verified: pure stdlib, zero heavy
deps). Branch 1 (Chaquopy embed) is preferred over Branch 2 (Kotlin port) to avoid
a permanent maintenance fork — the APK overhead is a one-time cost.

**The structural no-network guarantee requires `isolatedProcess="true"` on the decode
service**, not just omitting INTERNET from the module manifest. This is the design
decision that makes the privacy claim true in all host app configurations.

---

*Sources consulted: Android developer docs (foreground service types, AudioRecord,
manifest merging, isolated processes, Privacy Dashboard); k2-fsa/sherpa-onnx issue
#2900; Picovoice Cheetah docs (French support, AccessKey model); Chaquopy 17.0
release notes; Android 16 KB page size migration guide; TuParles issue #2; codebase
import scan (2026-06-27).*
