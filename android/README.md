# TuParles on Android — the dictaphone

Local, private FR/EN dictation on the phone. A fresh Kotlin/Compose rebuild
(2026-07): the whole point is that everything runs on your own silicon, and no
`INTERNET` permission ships. Speak, save, share — the audio never leaves the box
unless *you* push it out via the share sheet.

**Phase A** (record / save / share), **Phase B** (on-device transcription) and
**Phase C** (full-text search over transcripts) are in (see
`docs/research/2026-07-17-android-dictaphone-rebuild-design.md`): a real dictaphone you
can live with, that transcribes on-device when a model is bundled, falls back to
audio-only when it is not, and lets you search back through everything you have said.

> The Chaquopy + whisper.cpp proof-of-concept that came before is preserved in the
> git tag [`android-poc-0.1`](https://github.com/PLNech/TuParles/releases/tag/android-poc-0.1).
> It validated the engine on-device; this rebuild is the app that validation earned.

## What it does

| Feature | How |
|---|---|
| **Record** | A foreground `RecordingService` (type `microphone`) captures 16 kHz mono PCM16 via `AudioRecord`, saves a canonical WAV to app-private storage. A take survives screen-off and app-switch — the exact failure that motivated the rebuild. |
| **Notes** | Room database — `Note(id, wavPath, createdAt, durationS, transcript?, transcriptState, transcriptLang)`. Newest-first list with date + duration. |
| **Transcribe** (Phase B) | After a recording is saved, `TranscriptionManager` decodes the WAV on-device via the `:whisper` module (`language=auto`), off the UI lifecycle. The row shows a `transcription…` hint, then the transcript preview; tapping a decoded note expands the full text. No model bundled → the engine reports unavailable and the app stays a pure dictaphone. |
| **Search** (Phase C) | A search field filters the list live (250 ms debounce) via Room **FTS4** over the transcripts (`NoteFts` external-content table). Prefix matching as you type ("bon" → "bonjour"); each hit shows a snippet centred on the match. Notes with no transcript can't match — a hint says how many are hidden so the exclusion is never silent. |
| **Share** | A note's WAV goes out via the system share sheet (`FileProvider`, `ACTION_SEND`). Once a transcript exists, the share button offers **Partager le texte** alongside the audio. |
| **Delete** | With a confirmation dialog — the audio is the artifact, so we ask first. |

The UI is a single-activity **Compose** app: one big record/stop control with a live
level meter and timer, and the notes list beneath it. Material 3, dynamic colour on
Android 12+.

## Architecture

Single-activity Compose · ViewModel + StateFlow · **Hilt** DI · **Room** storage ·
minSdk 26 · targetSdk 36. Versions live in the `gradle/libs.versions.toml` catalog.

The core aligns with the portable-core contract sketched in
[issue #2](https://github.com/PLNech/TuParles/issues/2) — the same gesture as
desktop: separate the platform-agnostic notions from their Android adapters.

```
core/
  RecorderSession        # start/stop, emits (rms, elapsedMs) → AudioRecorderSession
  TranscriptionEngine    # suspend transcribe(wav) → Transcript
                         #   WhisperTranscriptionEngine binds the native :whisper module
                         #   (available=false when no model asset → graceful degrade)
  NotesRepository        # Room-backed (RoomNotesRepository)
```

Recording state flows through a single Hilt-singleton `RecorderStateHolder`, shared
between the service that owns the mic and the ViewModel that renders it — so the read
path has no Android on it and is trivially unit-testable.

```
app/src/main/java/pl/nech/tuparles/
  TuParlesApp.kt              @HiltAndroidApp — resumes interrupted transcripts on start
  core/Contracts.kt           RecorderSession, TranscriptionEngine, NotesRepository, Transcript
  core/WhisperTranscriptionEngine.kt  Phase B: process-scoped whisper.cpp singleton
  core/NoopTranscriptionEngine.kt     unused reference impl (available=false)
  data/                       Note, NoteDao, AppDatabase, RoomNotesRepository,
                              TranscriptState, Converters, Migrations (1→2, 2→3),
                              NoteFts (FTS4 index), FtsQuery (safe MATCH builder)
  record/                     AudioRecorderSession, Wav, WavDecoder, RecorderState(+Holder), RecordingService
  transcribe/TranscriptionManager.kt  post-record decode + persisted state machine
  di/AppModule.kt             Hilt wiring (Room + migrations + contract binds + app scope)
  ui/                         MainActivity, RecorderViewModel, RecorderScreen, Share, theme/
  util/Format.kt              duration / filename / timestamp (pure, unit-tested)
  util/TranscriptSnippet.kt   search-result excerpt centred on the match (pure, unit-tested)
```

The `:whisper` gradle module (vendored whisper.cpp + the fixed CMake `-O3`/NEON + JNI)
is kept untouched from the POC. Phase B's `:app` module depends on it via
`WhisperTranscriptionEngine`; the JNI decode runs only on-device, so everything around
it (WAV decode, state machine, migration) is isolated behind the interface and JVM-tested.

## Privacy by construction

No `INTERNET` permission is declared — the OS itself denies any socket.
`RECORD_AUDIO` is the only sensitive permission. Sharing is a local `ACTION_SEND`
intent: nothing leaves the device unless you send it yourself.

## Toolchain

Everything below is already on the build box except the Gradle distribution (the
wrapper fetches it).

| Component | Version |
|---|---|
| Android Gradle Plugin | 8.9.0 |
| Gradle | 8.11.1 |
| Kotlin | 2.0.21 |
| KSP | 2.0.21-1.0.28 |
| JDK | 21 |
| compileSdk / targetSdk | 36 |
| minSdk | 26 |
| Hilt | 2.52 · Room 2.6.1 · Compose BOM 2024.10.01 |
| NDK (for `:whisper`, Phase B) | 27.1.12297006 |

## Build

```bash
export JAVA_HOME=$HOME/.sdkman/candidates/java/current   # JDK 21
export ANDROID_HOME=$HOME/Android/Sdk
cd android
./gradlew assembleDebug        # → app/build/outputs/apk/debug/app-debug.apk (~45 MB, no model)

# For on-device STT, fetch a model first (gitignored, never committed):
./scripts/fetch-android-model.sh          # base, 142 MB → ~186 MB APK
./scripts/fetch-android-model.sh large    # large-v3-turbo-q5_0, 547 MB (slower, flawless)
```

`local.properties` (gitignored) just needs `sdk.dir=$HOME/Android/Sdk`. Without a model
the ~45 MB APK still records and shares — it just skips transcription. Build with the
base model and the APK is ~186 MB (the model rides along as an **uncompressed asset**;
`androidResources { noCompress += "bin" }`). The model reaches the device **inside the
APK** — there is no `INTERNET` permission, so nothing is ever downloaded at runtime; to
keep the APK lean you can instead `adb push` a model into the app's files dir.

## Install / use

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n pl.nech.tuparles/.ui.MainActivity
adb logcat -s TuParles         # follow the mic lifecycle
```

The app requests `RECORD_AUDIO` (and notifications on Android 13+) on first tap.

## Tests

```bash
./gradlew testDebugUnitTest                                # pure-JVM
ANDROID_SERIAL=<device> ./gradlew connectedDebugAndroidTest  # on-device (needs a device)
```

- **`FormatTest`** — duration formatting (clamp / truncate edges) and note filenames.
- **`RecorderViewModelTest`** — the ViewModel combines notes + recorder state, delete
  forwards to the repository, and search filters to matching transcripts (prefix, live),
  counts the un-transcribed notes hidden from results, and restores the full list when
  cleared (fake repo, `StandardTestDispatcher`).
- **`WavDecoderTest`** — the WAV round-trip (`writeWav` → `decodeWavToFloats`) that
  feeds whisper: PCM16 recovers to normalised floats in `[-1, 1]`, empty-safe.
- **`TranscriptionManagerTest`** — the state machine: engine available → `DONE`,
  unavailable → `UNAVAILABLE` (engine never called), throws → `FAILED` (audio kept),
  already-`DONE` is idempotent, and `resumePending` re-decodes interrupted notes.
- **`MigrationTest`** — `MIGRATION_1_2` emits exactly the two additive `ALTER`s;
  `MIGRATION_2_3` creates the FTS4 virtual table + the four content-sync triggers +
  `rebuild`, and never drops or deletes from `notes`. (A real device upgrade via
  `MigrationTestHelper` needs a device — untested here.)
- **`FtsQueryTest`** — free text → safe prefix `MATCH`: stars per token, stray
  quotes/operators neutralised, blank/punctuation-only → null (show the full list).
- **`TranscriptSnippetTest`** — the search excerpt centres on the match, adds ellipses
  only where trimmed, and never cuts mid-word.

37 unit tests, all on the JVM. The native whisper decode and the FTS index build run
only on-device.

## Next

- **Phase B follow-ups**: the model sweet-spot (base vs small vs large-v3-turbo) is
  [issue #13](https://github.com/PLNech/TuParles/issues/13); on-device decode
  quality/speed is confirmed only on the Fairphone 6 (no AVD on the build box).
- **Phase C on-device confirm**: the FTS4 index build + live search are JVM-tested; the
  actual `MIGRATION_2_3` upgrade and search over a populated DB are confirmed only by
  build-time SQL assertions (the DDL was captured verbatim from Room's generated
  schema), not yet exercised on a device.
