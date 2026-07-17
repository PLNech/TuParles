package pl.nech.tuparles.transcribe

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.di.ApplicationScope
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Drives a note from recorded audio to a decoded transcript, off the UI lifecycle.
 *
 * **Why an application-scoped coroutine, not WorkManager**: transcription is
 * best-effort by doctrine — the audio is the durable artifact and the desktop can
 * always re-decode a WAV at higher quality, so cross-process-death durability buys
 * little. A process-scoped scope keeps the decode warm against the process-scoped
 * whisper singleton (no reload per note), survives screen-off / app-switch (it is not
 * tied to any ViewModel), and — crucially — keeps the whole state machine unit-testable
 * on the JVM (no Hilt-Worker / Configuration.Provider wiring, no device). Notes left
 * PENDING/RUNNING when the process died are picked up by [resumePending] at app start.
 *
 * State machine (persisted on [Note.transcriptState]):
 *   saved → PENDING → RUNNING → DONE            (engine available, decode ok)
 *                              ↘ FAILED          (engine threw; audio still safe)
 *   saved → UNAVAILABLE                          (no engine/model → Phase A behaviour)
 */
@Singleton
class TranscriptionManager @Inject constructor(
    private val engine: TranscriptionEngine,
    private val notes: NotesRepository,
    @ApplicationScope private val scope: CoroutineScope,
) {

    /** Called right after a note is saved. Marks state and (if possible) kicks off decode. */
    fun onNoteSaved(noteId: Long) {
        scope.launch { process(noteId) }
    }

    /** Re-enqueue notes interrupted mid-decode (or never started) by a previous process. */
    fun resumePending() {
        scope.launch {
            for (note in notes.pendingTranscripts()) process(note.id)
        }
    }

    /**
     * The full lifecycle for one note, sequential and side-effecting on the repository.
     * Public (not private) so tests can drive it deterministically without the scope.
     */
    suspend fun process(noteId: Long) {
        val note = notes.get(noteId) ?: return
        if (note.transcriptState == TranscriptState.DONE) return // already decoded, idempotent

        if (!engine.available) {
            if (note.transcriptState != TranscriptState.UNAVAILABLE) {
                notes.update(note.copy(transcriptState = TranscriptState.UNAVAILABLE))
            }
            return
        }

        notes.update(note.copy(transcriptState = TranscriptState.RUNNING))
        try {
            val transcript = engine.transcribe(note.wavPath)
            notes.update(
                note.copy(
                    transcript = transcript.text,
                    transcriptLang = transcript.language,
                    transcriptState = TranscriptState.DONE,
                ),
            )
        } catch (e: Throwable) {
            Log.w(TAG, "Transcription failed for note $noteId; audio preserved", e)
            notes.update(note.copy(transcriptState = TranscriptState.FAILED))
        }
    }

    private companion object {
        const val TAG = "TuParles"
    }
}
