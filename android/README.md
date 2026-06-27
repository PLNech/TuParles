# TuParles on Android — the spike

Local, private FR/EN dictation on the phone, sharing **one** Python core with the
desktop daemon (no Kotlin re-port, no dual-maintenance tax). This is the embed
path from issue #2 / the packaging research: **Chaquopy carries the postprocess
core; the STT engine runs native (whisper.cpp via JNI) on the Kotlin side.**

## The build ladder

Each rung is a shippable "tested tonight" — whatever we reach is a real result.

| Rung | Proves | Status |
|---|---|---|
| **0** · hello-world APK | the device loop (build → install → run) | ✅ builds (3.0M) |
| **1** · Chaquopy runs `postprocess()` | the **Python embed** | ✅ builds (37.7M) |
| **2** · mic → whisper.cpp (JNI) → raw text | the **engine on-device** | ⏳ gated on the FR/EN code-switch de-risk |
| **3** · mic → whisper → `postprocess()` → text | the **MVP loop** | ⏳ |

The postprocess core is the **same `src/tuparles`** the desktop daemon and eval
harness use — wired in via `chaquopy { sourceSets { main { srcDir("../../src") } } }`,
no copy. The lean chain (`pipeline` → casing/lexicon/punctuation/repeats/syntax/
`syntax_features` → `config_core`) is pure stdlib, so **no pip deps**; the heavy
desktop modules (daemon, ui, engine) ship as unused bytecode.

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

## Build

```bash
export ANDROID_HOME=$HOME/Android/Sdk
cd android
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

`local.properties` (gitignored) just needs `sdk.dir=$HOME/Android/Sdk`.

## Test on the phone tonight

```bash
adb devices                 # confirm the phone is listed (USB debugging on)
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n pl.nech.tuparles/.MainActivity
adb logcat | grep -i tuparles   # if it misbehaves
```

Rung 1 should show the hardcoded code-switch line and its `postprocess()` output
(capitalised, `virgule`→`,`, `point`→`.`, the FR/EN switch intact).

## Privacy by construction

No `INTERNET` permission is declared in the manifest — the OS itself denies any
socket. `RECORD_AUDIO` arrives with the mic at Rung 2. Nothing leaves the device.
