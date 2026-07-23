package pl.nech.tuparles.transcribe

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.NoteSegment
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.di.ApplicationScope
import pl.nech.tuparles.model.ModelResolver
import java.util.concurrent.atomic.AtomicInteger
import pl.nech.tuparles.record.ClosedSegment
import pl.nech.tuparles.record.RecorderPreferences
import pl.nech.tuparles.record.RecorderStateHolder
import pl.nech.tuparles.record.SAMPLE_RATE
import pl.nech.tuparles.record.decodeWavToFloats
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The rolling committed transcript — the record-minutes-and-pray fix. While a note is
 * recorded, completed silence-bounded segments decode through the engine's **committed**
 * path (they wait, never skip) in order, one at a time, and each is persisted the instant
 * it lands. What the speaker sees settle is what is kept: a process death mid-recording
 * still leaves every segment already written, and stop only decodes the *remainder* — never
 * the whole take again.
 *
 * Doctrines baked in:
 *  - **Never replace committed text.** A segment, once decoded and persisted, is final; the
 *    finalisation only *appends* the tail. A visible mishear beats a silent rewrite.
 *  - **Committed beats partial.** Segment decodes hold the gate; the live tail-preview
 *    yields to them (its tryLock skips). Order is preserved even across a model switch —
 *    the next segment simply waits for the new context.
 *  - **Graceful degradation.** [shouldArm] is false when the feature is off or no model is
 *    loaded, so recording proceeds exactly as before and the note takes the post-hoc path.
 *
 * A single note is recorded at a time; [begin]/[submit]/[finish] drive one session.
 */
@Singleton
class RollingTranscriber @Inject constructor(
    private val engine: TranscriptionEngine,
    private val notes: NotesRepository,
    private val stateHolder: RecorderStateHolder,
    private val prefs: RecorderPreferences,
    private val resolver: ModelResolver,
    @ApplicationScope private val scope: CoroutineScope,
) {
    private var channel: Channel<ClosedSegment>? = null
    private var worker: Job? = null
    private var noteId: Long = 0
    private val committedTexts = mutableListOf<String>()
    // Segments submitted but not yet decoded — the live decode backlog. On a slow model
    // this grows behind the speaker; surfaced as the post-stop "transcription… (N)" count.
    private val pendingSegments = AtomicInteger(0)

    /**
     * Whether to commit segments live for a new recording: feature on AND a model loaded
     * AND that model is fast enough to keep up ([ModelSpec.liveCapable]). A slow model
     * degrades honestly to the post-stop path — piling decodes up behind the speaker helps
     * no one. Honesty beats the toggle: even with the setting ON, a slow model still degrades.
     */
    fun shouldArm(): Boolean =
        prefs.rollingTranscriptEnabled && engine.available && resolver.currentLiveCapable()

    /**
     * The user asked for the live transcript (toggle on, model loaded) but the active model
     * is too slow for it — so we degraded to a post-stop decode and should say so in the UI.
     */
    fun isLiveDegraded(): Boolean =
        prefs.rollingTranscriptEnabled && engine.available && !resolver.currentLiveCapable()

    /** Segments queued for decode but not yet committed (the live backlog). */
    fun pendingCount(): Int = pendingSegments.get()

    /** Open a rolling session for [noteId]; segments submitted next decode in order. */
    fun begin(noteId: Long) {
        worker?.cancel()
        this.noteId = noteId
        committedTexts.clear()
        pendingSegments.set(0)
        stateHolder.clearCommitted()
        val ch = Channel<ClosedSegment>(Channel.UNLIMITED)
        channel = ch
        worker = scope.launch {
            for (segment in ch) {
                decodeAndPersist(segment)
                pendingSegments.decrementAndGet()
            }
        }
    }

    /** Hand a completed segment to the decode queue (non-blocking; ordering preserved). */
    fun submit(segment: ClosedSegment) {
        if (channel?.trySend(segment)?.isSuccess == true) pendingSegments.incrementAndGet()
    }

    /** Abandon the session without finalising a note (nothing was captured). */
    fun cancel() {
        worker?.cancel()
        worker = null
        channel?.close()
        channel = null
        committedTexts.clear()
        pendingSegments.set(0)
        stateHolder.clearCommitted()
    }

    /**
     * Recording stopped. Drain the queued segments, decode the [remainder] (audio after the
     * last committed segment) as the final committed segment, then finalise the note to DONE.
     * The full WAV is never re-decoded — only the tail. [durationS] is the note's real length.
     */
    suspend fun finish(remainder: ClosedSegment?, durationS: Float) {
        channel?.close()
        worker?.join()
        channel = null
        worker = null

        if (remainder != null) decodeAndPersist(remainder)

        val note = notes.get(noteId) ?: return
        notes.update(
            note.copy(
                transcript = committedTexts.joinToString(" ").trim().ifEmpty { null },
                transcriptState = TranscriptState.DONE,
                durationS = durationS,
            ),
        )
        stateHolder.clearCommitted()
    }

    /** Decode one segment on the committed path and, if it produced text, persist + publish. */
    private suspend fun decodeAndPersist(segment: ClosedSegment) {
        val text = try {
            engine.transcribeSamplesCommitted(segment.samples)?.text?.trim()
        } catch (e: Throwable) {
            // A mid-recording engine failure (e.g. model deleted) loses this segment's text,
            // never the recording: the WAV survives for a desktop re-decode. Best effort.
            Log.w(TAG, "rolling segment ${segment.index} decode failed; audio preserved", e)
            null
        }
        if (text.isNullOrBlank()) return
        notes.addSegment(
            NoteSegment(
                noteId = noteId,
                segmentIndex = segment.index,
                text = text,
                startSample = segment.startSample.toLong(),
                endSample = segment.endSample.toLong(),
            ),
        )
        committedTexts += text
        stateHolder.setCommitted(committedTexts.joinToString(" ").trim())
    }

    /**
     * Recover notes left in RECORDING by a process death. Their committed segments survive;
     * the transcript is rebuilt from them. When the WAV made it to disk (a crash during
     * finalisation), the remainder after the last committed segment is decoded post-hoc so no
     * audio is lost; otherwise the committed text stands on its own (the un-committed tail was
     * never persisted — the WAV write path stays untouched, written only at stop).
     */
    fun recover() {
        scope.launch {
            for (note in notes.recordingNotes()) recoverOne(note.id)
        }
    }

    private suspend fun recoverOne(id: Long) {
        val note = notes.get(id) ?: return
        val segments = notes.segmentsFor(id)
        val texts = segments.map { it.text }.toMutableList()
        val wav = File(note.wavPath)

        var durationS = segments.maxOfOrNull { it.endSample }?.let { it.toFloat() / SAMPLE_RATE } ?: 0f

        if (wav.exists() && engine.available) {
            runCatching {
                val floats = decodeWavToFloats(wav)
                durationS = floats.size.toFloat() / SAMPLE_RATE
                val lastEnd = segments.maxOfOrNull { it.endSample }?.toInt() ?: 0
                if (lastEnd < floats.size) {
                    val remainder = floats.copyOfRange(lastEnd, floats.size)
                    val rem = engine.transcribeSamplesCommitted(remainder)?.text?.trim()
                    if (!rem.isNullOrBlank()) {
                        val idx = (segments.maxOfOrNull { it.segmentIndex } ?: -1) + 1
                        notes.addSegment(
                            NoteSegment(
                                noteId = id,
                                segmentIndex = idx,
                                text = rem,
                                startSample = lastEnd.toLong(),
                                endSample = floats.size.toLong(),
                            ),
                        )
                        texts += rem
                    }
                }
            }.onFailure { Log.w(TAG, "recovery remainder decode failed for note $id", it) }
        }

        val transcript = texts.joinToString(" ").trim()
        notes.update(
            note.copy(
                transcript = transcript.ifEmpty { null },
                // Text recovered → DONE. Nothing at all (crashed before the first segment, no
                // audio on disk) → FAILED: visible, never silently dropped.
                transcriptState = if (transcript.isNotEmpty()) TranscriptState.DONE else TranscriptState.FAILED,
                durationS = durationS,
            ),
        )
    }

    private companion object {
        const val TAG = "TuParles"
    }
}
