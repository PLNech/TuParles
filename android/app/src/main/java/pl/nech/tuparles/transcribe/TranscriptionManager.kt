package pl.nech.tuparles.transcribe

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.di.ApplicationScope
import pl.nech.tuparles.model.PendingWork
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
 *   saved → PENDING (no model)                  (lean APK, no model yet — "en attente
 *                                                d'un modèle"; auto-decodes once one lands)
 *
 * With the lean-APK change (#13) a fresh install has no model, so an un-decodable note
 * stays PENDING rather than UNAVAILABLE: it is genuinely *waiting for a model*, and
 * [retryPending] — called when a download completes — sweeps it up. The audio is always
 * saved regardless; transcription is never allowed to block or lose a recording.
 */
@Singleton
class TranscriptionManager @Inject constructor(
    private val engine: TranscriptionEngine,
    private val notes: NotesRepository,
    @ApplicationScope private val scope: CoroutineScope,
) : PendingWork {

    /** Called right after a note is saved. Marks state and (if possible) kicks off decode. */
    fun onNoteSaved(noteId: Long) {
        scope.launch { process(noteId) }
    }

    /** Re-enqueue notes interrupted mid-decode, never started, or waiting for a model. */
    fun resumePending() {
        scope.launch {
            for (note in notes.pendingTranscripts()) process(note.id)
        }
    }

    /** [PendingWork]: a model just became available — decode whatever was waiting. */
    override fun retryPending() = resumePending()

    /**
     * The full lifecycle for one note, sequential and side-effecting on the repository.
     * Public (not private) so tests can drive it deterministically without the scope.
     */
    suspend fun process(noteId: Long) {
        val note = notes.get(noteId) ?: return
        if (note.transcriptState == TranscriptState.DONE) return // already decoded, idempotent

        if (!engine.available) {
            // No model yet (lean APK / download not finished): the note waits for one.
            if (note.transcriptState != TranscriptState.PENDING) {
                notes.update(note.copy(transcriptState = TranscriptState.PENDING))
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
