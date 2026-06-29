# TuParles on Android

Local, private FR/EN dictation on the phone, sharing **one** Python core with the
desktop daemon (no Kotlin re-port, no dual-maintenance tax). This is the embed
path from issue #2 / the packaging research: **Chaquopy carries the postprocess
core; the STT engine runs native (whisper.cpp via JNI) on the Kotlin side.**

What began as a build-ladder spike (below) is now an app you can live with:
everything runs on your own silicon, and no `INTERNET` permission ships in release.

## The surfaces — one backbone, many faces

Recording and decoding live in a single foreground `DictationService` (type
`microphone`); every surface below is a thin observer of its process `StateFlow`,
so they share one model, one postprocess, one telemetry path — and a take in
flight survives screen rotation or backgrounding.

| Surface | What it is |
|---|---|
| **Scratchpad** (launcher) | Dictate or type, copy/share, pick model/language, flip private mode. |
| **Keyboard** (`InputMethodService`) | A pure-TuParles keyboard: dictates into any app's field. Live meter, language cycle, **📝 record-fix** key. |
| **Historique** | Newest-first take list with 👍/👎/✏️ labelling — the learning store made visible. |
| **Réglages** | Engine/model/language, privacy block, **decode-thread** perf knob, live SIMD/core readout. |
| **Widget** | One-tap dictate from the home screen → clipboard + notification. |
| **Recognizer** (`RecognitionService`) | Set as the device voice input → the system mic-button goes on-device. |

**Private mode** is the master switch: ON suppresses file logging, analytics/sync,
and raw take audio — but never your own dictation result. The **learning loop**:
dictate → correct (in any keyboard) → return to TuParles → 📝 to capture the
corrected form; telemetry carries shape (counts, edit distance, RTF, votes), never
the text.

## The build ladder — all rungs reached ✅

| Rung | Proves | Status |
|---|---|---|
| **0** · hello-world APK | the device loop (build → install → run) | ✅ on Fairphone 6 |
| **1** · Chaquopy runs `postprocess()` | the **Python embed** | ✅ ran on-device |
| **2** · mic → whisper.cpp (JNI) → raw text | the **engine on-device** | ✅ native fp16 build |
| **3** · mic → whisper → `postprocess()` → text | the **MVP loop** | ✅ full loop verified |

The full loop runs end-to-end on the phone: mic (16k mono `AudioRecord`) → native
whisper.cpp → embedded-CPython `postprocess()` → saved take. The postprocess core
is the **same `src/tuparles`** the desktop daemon and eval harness use — wired via
`chaquopy { sourceSets { main { srcDir("../../src") } } }`, no copy. The lean chain
(`pipeline` → casing/lexicon/punctuation/repeats/syntax/`syntax_features` →
`config_core`) is pure stdlib, so **no pip deps**; heavy desktop modules ship as
unused bytecode.

## De-risk verdict (Fairphone 6, Dimensity 7300)

On-device FR/EN code-switch is **viable**. Two findings that cost the most to learn:

1. **`-O3` is non-negotiable for the native build.** A debug APK compiles
   `ggml-cpu`/`ggml-base` at `-O0` → ~50× slower (88s → 1.5s for base). The fix
   forces `-O3` on every ggml target in `jni/whisper/CMakeLists.txt`, regardless
   of build type.
2. **Language must be `auto`, not hardcoded `"en"`.** The grafted JNI pinned
   `params.language = "en"`, which *translated* French to English. With `auto`,
   whisper transcribes each language as itself.

Quality/speed ladder (per ~4s clip), validated against recorded takes:

| Model | Speed | Code-switch quality |
|---|---|---|
| base (142M) | ~1.5s | French stays French, but fumbles tech vocab (pipeline→"payplane") |
| large-v3-turbo-q5 (547M) | ~30-44s | **flawless** — *"Alors j'ai fait un quick refactor du pipeline, faut que je commite avant la review"* |

small/medium are the untested sweet spot. base is bundled as the fast default;
push a larger model to use it (see below).

## The capture harness (experimental POC)

A 12-prompt FR/EN code-switch corpus, each with a record button. Per take it runs
the same two stages as desktop and saves `{wav, raw, cleaned}` to
`getExternalFilesDir("captures")`. Two toggles (*"it's a setting"* doctrine):

- **Langue**: `auto` (detect) · `fr` · `en` (force).
- **Postprocess**: ON (apply `pipeline.postprocess()`) · OFF (raw decode).

**📧 Envoyer mes prises à dev@nech.pl** shares all takes via a local
`ACTION_SEND_MULTIPLE` intent (FileProvider content URIs) — the email app does the
sending; we still declare no `INTERNET` permission.

## Pinned version combo (the part that fights you)

Every piece below is already on this box except the Gradle distribution (the
wrapper fetches it). Chaquopy 17.0 supports AGP 8.9–8.13, which lets us use
`compileSdk 36` (the platform we have) with no SDK install.

| Component | Version | Why |
|---|---|---|
| Chaquopy | 17.0 | current; AGP 8.9–8.13, Python 3.13 |
| Android Gradle Plugin | 8.9.0 | in Chaquopy 17's window |
| Gradle | 8.11.1 | AGP 8.9 floor |
| Kotlin | 2.0.21 | pairs with AGP 8.9 |
| JDK | 21 | sdkman default here |
| compileSdk / targetSdk | 36 | `platforms/android-36` present |
| minSdk | 24 | Chaquopy 17 floor (~97% of devices) |
| Chaquopy Python | 3.12 | matches the core's `>=3.11` |
| NDK | 27.1.12297006 | for whisper.cpp (Rung 2) |

## Build the (self-contained) experimental APK

```bash
export ANDROID_HOME=$HOME/Android/Sdk
cd android
./scripts/fetch-android-model.sh        # base (142M) → assets, gitignored
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk  (~206M, model bundled)
```

`local.properties` (gitignored) just needs `sdk.dir=$HOME/Android/Sdk`. The model
is gitignored (>100M, over GitHub's limit) and fetched into `assets/models/`; the
APK ships it uncompressed (`noCompress "bin"`) so it loads in ~1s.

## Run / use a bigger model

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell pm grant pl.nech.tuparles android.permission.RECORD_AUDIO
adb shell am start -n pl.nech.tuparles/.ScratchpadActivity   # the app home
adb logcat -s TuParles            # follow decodes (timings, lang, RTF, chars)
```

The launcher is **ScratchpadActivity**; the original 12-prompt capture harness is
now **MainActivity** (`🎛 Capture`, reached from the scratchpad). Enable the
keyboard under *Réglages système → Langues et saisie*; set the recognizer under the
device's voice-input setting.

A fresh install uses the **bundled base** model. To use the flawless large model,
push it — the app prefers any model found in external files:

```bash
./scripts/fetch-android-model.sh large
adb push app/src/main/assets/models/ggml-large-v3-turbo-q5_0.bin \
  /sdcard/Android/data/pl.nech.tuparles/files/models/
```

Pull the recorded takes and the durable history/learning store:

```bash
adb pull /sdcard/Android/data/pl.nech.tuparles/files/captures   # harness {wav,raw,clean}
adb pull /sdcard/Android/data/pl.nech.tuparles/files/history     # takes.jsonl (learning store)
adb pull /sdcard/Android/data/pl.nech.tuparles/files/takes       # opt-in per-take WAVs
```

`history/takes.jsonl` is the learning store: one row per take with
`{raw, clean, corrected, vote}` + profiling (RTF, decode ms, model). The
**Historique** screen also exports it directly via the share sheet. Suppressed
entirely in private mode.

## Tests

```bash
./gradlew :app:testDebugUnitTest          # pure-JVM, framework-free (Text.kt helpers)
ANDROID_SERIAL=<device> ./gradlew :app:connectedDebugAndroidTest   # on-device
```

- **Unit (8)** — `Text.kt`: levenshtein edit-distance, `humanBytes`, `meterBar` (clamp/boost
  edges). No Android, no Robolectric — runs anywhere.
- **Instrumented (7, on a real device)** — the core pipeline end-to-end (Chaquopy
  postprocess + whisper.cpp model load + a full `Dictation.decode`), and the TakesStore
  JSONL codec round-trip (votes/corrections/profiling survive; garbage → null). The codec
  test does no file IO, so it never touches your real `takes.jsonl`.

## Privacy by construction

No `INTERNET` permission is declared in the manifest — the OS itself denies any
socket. `RECORD_AUDIO` is the only sensitive permission. Export is a local
`ACTION_SEND` intent: nothing leaves the device unless *you* send it from your own
email app.
