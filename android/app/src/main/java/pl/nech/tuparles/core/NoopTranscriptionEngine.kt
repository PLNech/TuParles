package pl.nech.tuparles.core

import javax.inject.Inject

/**
 * PHASE B PLACEHOLDER — wire the native `:whisper` module here.
 *
 * Phase A is a dictaphone: the audio is always kept (retranscribable on the desktop
 * with large-v3), and a note's `transcript` stays null until on-device STT lands.
 * This impl advertises itself as unavailable and throws if called, so nothing in
 * Phase A silently depends on transcription existing.
 */
class NoopTranscriptionEngine @Inject constructor() : TranscriptionEngine {
    override val available: Boolean = false

    override suspend fun transcribe(wavPath: String): Transcript =
        throw NotImplementedError("On-device transcription arrives in Phase B (issue #2 / #3).")
}
