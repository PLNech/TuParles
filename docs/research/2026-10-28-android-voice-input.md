# Android voice input — three doors, one engine (2026-10-28)

SwiftKey's microphone does not call a pluggable engine. Gboard does not
either. The apps that actually land on-device Whisper into other keyboards
open three doors, and they share one decode runtime.

## What the field does

| app | engine | how another keyboard reaches it |
|---|---|---|
| FUTO Voice Input | whisper.cpp | voice IME subtype (HeliBoard switches to it) and `ACTION_RECOGNIZE_SPEECH` (a floating panel) |
| whisperIME | Whisper TFLite / ONNX | the same two, plus a `RecognitionService` for Settings → Saisie vocale |
| WhisperTypeKeyboard | sherpa-onnx | a full QWERTY with a mic. No second keyboard needed |
| Sayboard | Vosk | voice IME + `RecognitionService`. The architecture, not the model |
| Kõnele | Kaldi, then reused | the original `speechutils` shape the others copy |

Gboard and Samsung Keyboard hardcode their own recognizer. Setting a
default does not move them.

## What we ship

The existing whisper.cpp engine. No second runtime. sherpa-onnx would mean
another model format and another JNI stack for a gain we have not measured
on this phone.

- **Voice IME**, auxiliary subtype. HeliBoard, FlorisBoard, AnySoftKeyboard
  switch to it from their mic key. ABC returns to the previous keyboard.
- **`ACTION_RECOGNIZE_SPEECH`**. This is the intent SwiftKey's mic starts.
  Android shows a chooser the first time. The activity records, decodes,
  returns `EXTRA_RESULTS`.
- **`RecognitionService`**. Settings → Langues et saisie → Saisie vocale.
  Apps that bind the default recognizer get this. SwiftKey's mic does not.

## What we did not copy

A full QWERTY. TuParles is the dictation strip, not a replacement keyboard.
Auto-stop via Silero VAD. FUTO and whisperIME endpoint on silence. Ours
stops when the user taps Terminer or Stop. A 30-second cap is theirs, not
ours. The take length is the recorder's, not a voice-input limit.

## Open

Play internal still needs the Play service-account JSON. It is not in the
1Password items that hold the upload key. The signed APK is the sideload
path until that file exists.
