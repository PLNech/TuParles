---
id: 1
status: done
created: 2026-10-28
owner: pln
---
# A long take vanished after Stop while a system approval screen was up

Field report, 2026-10-28, Fairphone. A long transcription was still running
(the UI kept saying it was transcribing and kept going) when a Google approval
activity opened over the app. The user came back, tapped Stop, and the take
never appeared in the notes list.

## Why this can happen in the current code

`NoteDao.observeAll` hides every row whose `transcriptState` is `RECORDING`
until the row finalises. On the rolling path the note is inserted at start in
that state, and the WAV is written only inside `RecordingService.stopAndSave`.

`onDestroy` does the opposite of a save: it calls `recorder.stop()`, cancels
the service scope, and never writes the WAV or flips the row out of
`RECORDING`. A foreground service the system kills while another activity owns
the screen (permission / account approval, low memory, process death) takes
that path. The row stays `RECORDING` forever, so the list query never shows
it, and the audio is gone.

`RollingTranscriber` already recovers committed segments after a process death.
That recovery does not cover a take whose WAV was never written, and nothing
logs the destroy-while-recording path, so the field report has no trail.

## What landed

The mic spills into a growing WAV from the first sample, on both the rolling
path and the post-hoc path. `onDestroy` while recording abandons the mic
(no whole-take copy on the main thread) and runs `salvageInterruptedTake`:
audio on disk with no committed text becomes `PENDING` and is queued for
decode; committed text becomes `DONE` and is not rewritten; samples that
never reached disk become a visible `FAILED` row; an empty instant-stop
still deletes the note. The log line is `take <path>: note= durationS= pcm=`
and carries no transcript text.

On-device: the debug install sits beside the Play copy. `drive-debug.sh`
started and stopped a take over adb; the status line reported a visible
note (`visible=2 recording=0 newest=2 state=RUNNING durationS=5.0`) with no
model on the device, so decode stays queued. The destroy-under-a-system-screen
path is still a field check.

## Completion criteria

- Stop, process death, and `onDestroy` while recording all leave a row the
  list can show. Audio that reached the mic is on disk before the service
  dies, or the failure is a visible `FAILED` row, never a silent absence.
- The rolling path and the post-hoc path both hold. An empty instant-stop
  still drops the empty note.
- A log line names the path taken (saved, recovered, dropped-empty,
  destroyed-while-recording) with note id, duration, and pcm length. No
  transcript text in the log.
- A JVM test drives the destroy-while-recording case and asserts the row is
  visible afterwards. On-device check: start a long take, background the app
  behind another activity, stop, and see the note.
