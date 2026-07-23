package pl.nech.tuparles.data

/**
 * Lifecycle of a note's on-device transcript. The audio is always the source of
 * truth (a dictaphone keeps the WAV); the transcript is best-effort and re-doable
 * on the desktop, so every non-DONE state degrades gracefully — the note is never
 * blocked or lost by transcription.
 *
 * - [NONE]        never queued (legacy rows, or transcription not attempted yet).
 * - [RECORDING]   the note is being recorded right now, its rolling transcript growing
 *                 segment by segment; kept out of the notes list until it finalises.
 * - [PENDING]     queued for decode, waiting for the engine.
 * - [RUNNING]     the engine is decoding this note now.
 * - [DONE]        [Note.transcript] holds the decoded text.
 * - [FAILED]      the decode threw; the audio remains, retry/desktop can recover it.
 * - [UNAVAILABLE] no on-device engine/model present — Phase A behaviour, audio only.
 */
enum class TranscriptState {
    NONE,
    RECORDING,
    PENDING,
    RUNNING,
    DONE,
    FAILED,
    UNAVAILABLE,
    ;

    /** Whether a decode is queued or in flight (the row shows a "transcribing" hint). */
    val inFlight: Boolean get() = this == PENDING || this == RUNNING
}
