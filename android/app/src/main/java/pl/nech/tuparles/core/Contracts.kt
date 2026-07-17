package pl.nech.tuparles.core

import kotlinx.coroutines.flow.Flow
import pl.nech.tuparles.data.Note

/**
 * The portable core contract sketched in issue #2: a small boundary between the
 * platform-agnostic notions (record a session, transcribe audio, store notes) and
 * their Android adapters. This app is the first host of that contract, not a dead
 * end — when the library extraction (#2) lands, these three interfaces are the seam.
 */

/** Captures 16 kHz mono PCM16 from the mic. start() opens it, stop() returns samples. */
interface RecorderSession {
    /**
     * @param onLevel realtime feedback per audio chunk: (rms 0..1, elapsedMs) so a
     *   surface can paint a live meter + timer.
     */
    fun start(onLevel: (rms: Float, elapsedMs: Long) -> Unit)

    /** Stops the mic and returns the captured PCM16 samples. */
    fun stop(): ShortArray
}

/** The result of decoding audio to text. Model/language are for provenance. */
data class Transcript(val text: String, val language: String?, val model: String)

/**
 * Decodes recorded audio to text. Phase B binds the native whisper.cpp engine
 * (the vendored `:whisper` module) behind this; Phase A ships a no-op so the
 * dictaphone never depends on the engine being present.
 */
interface TranscriptionEngine {
    /** Whether on-device transcription is wired up (false until Phase B). */
    val available: Boolean

    suspend fun transcribe(wavPath: String): Transcript
}

/** Persistence for recorded notes. Room-backed on Android (see data/). */
interface NotesRepository {
    fun observeNotes(): Flow<List<Note>>
    suspend fun add(note: Note): Long
    suspend fun update(note: Note)
    suspend fun delete(note: Note)
    suspend fun get(id: Long): Note?

    /** Notes whose transcript is queued or was interrupted mid-decode (resume on start). */
    suspend fun pendingTranscripts(): List<Note>
}
