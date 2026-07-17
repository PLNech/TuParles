# TuParles on Android — the dictaphone

Local, private FR/EN dictation on the phone. A fresh Kotlin/Compose rebuild
(2026-07): the whole point is that everything runs on your own silicon, and no
`INTERNET` permission ships. Speak, save, share — the audio never leaves the box
unless *you* push it out via the share sheet.

This is **Phase A** of the rebuild (see
`docs/research/2026-07-17-android-dictaphone-rebuild-design.md`): a real dictaphone
you can live with. On-device transcription (Phase B) and full-text search (Phase C)
layer on behind the interfaces already in place.

> The Chaquopy + whisper.cpp proof-of-concept that came before is preserved in the
> git tag [`android-poc-0.1`](https://github.com/PLNech/TuParles/releases/tag/android-poc-0.1).
> It validated the engine on-device; this rebuild is the app that validation earned.

## What Phase A does

| Feature | How |
|---|---|
| **Record** | A foreground `RecordingService` (type `microphone`) captures 16 kHz mono PCM16 via `AudioRecord`, saves a canonical WAV to app-private storage. A take survives screen-off and app-switch — the exact failure that motivated the rebuild. |
| **Notes** | Room database — `Note(id, wavPath, createdAt, durationS, transcript?)`. Newest-first list with date + duration. |
| **Share** | A note's WAV goes out via the system share sheet (`FileProvider`, `ACTION_SEND`). |
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
                         #   Phase A ships NoopTranscriptionEngine (available=false)
                         #   Phase B binds the native :whisper module here
  NotesRepository        # Room-backed (RoomNotesRepository)
```

Recording state flows through a single Hilt-singleton `RecorderStateHolder`, shared
between the service that owns the mic and the ViewModel that renders it — so the read
path has no Android on it and is trivially unit-testable.

```
app/src/main/java/pl/nech/tuparles/
  TuParlesApp.kt              @HiltAndroidApp
  core/Contracts.kt           RecorderSession, TranscriptionEngine, NotesRepository, Transcript
  core/NoopTranscriptionEngine.kt   Phase B placeholder
  data/                       Note, NoteDao, AppDatabase, RoomNotesRepository
  record/                     AudioRecorderSession, Wav, RecorderState(+Holder), RecordingService
  di/AppModule.kt             Hilt wiring (Room + contract binds)
  ui/                         MainActivity, RecorderViewModel, RecorderScreen, Share, theme/
  util/Format.kt              duration / filename / timestamp (pure, unit-tested)
```

The `:whisper` gradle module (vendored whisper.cpp + the fixed CMake + JNI) is kept
untouched for Phase B. Phase A's `:app` module does **not** depend on it, but the
overall build (including `:whisper`) stays green.

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
./gradlew assembleDebug        # → app/build/outputs/apk/debug/app-debug.apk (~19 MB)
```

`local.properties` (gitignored) just needs `sdk.dir=$HOME/Android/Sdk`. Phase A needs
**no model** — the APK is lean.

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
- **`RecorderViewModelTest`** — the ViewModel combines notes + recorder state, and
  delete forwards to the repository (fake repo, `StandardTestDispatcher`).

## Next

- **Phase B — on-device STT**: bind `:whisper` behind `TranscriptionEngine`, decode
  post-recording, fill `Note.transcript`. Model fetched by script at build (never
  committed), `language=auto`, `-O3` native build — the three POC lessons.
- **Phase C — search**: Room FTS over transcripts, keyword search, share the text.
