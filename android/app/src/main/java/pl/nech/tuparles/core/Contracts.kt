package pl.nech.tuparles.core

import kotlinx.coroutines.flow.Flow
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.NoteSegment
import pl.nech.tuparles.record.ClosedSegment
import pl.nech.tuparles.record.SegmentationConfig

/**
 * The portable core contract sketched in issue #2: a small boundary between the
 * platform-agnostic notions (record a session, transcribe audio, store notes) and
 * their Android adapters. This app is the first host of that contract, not a dead
 * end — when the library extraction (#2) lands, these three interfaces are the seam.
 */

/**
 * Optional live segmentation for the rolling committed transcript: a [config] and a callback
 * fired (on the mic thread) each time a silence-bounded segment closes during recording. The
 * segmenter is a pure observer of the same PCM the WAV is written from — it never touches the
 * write path. Absent (null [start] arg) → no rolling, exactly the prior behaviour.
 */
class SegmentationSink(
    val config: SegmentationConfig,
    val onSegmentClosed: (ClosedSegment) -> Unit,
)

/** Captures 16 kHz mono PCM16 from the mic. start() opens it, stop() returns samples. */
interface RecorderSession {
    /**
     * @param onLevel realtime feedback per audio chunk: (rms 0..1, elapsedMs) so a
     *   surface can paint a live meter + timer.
     * @param segmentation when non-null, splits the stream into committed segments live
     *   (the rolling transcript); when null, records as a single take like before.
     */
    fun start(
        onLevel: (rms: Float, elapsedMs: Long) -> Unit,
        segmentation: SegmentationSink? = null,
    )

    /** Stops the mic and returns the captured PCM16 samples. */
    fun stop(): ShortArray

    /**
     * The most recent few seconds of captured audio as normalised floats ([-1, 1], 16 kHz
     * mono), for the live-partials preview (#42). Thread-safe; safe to call mid-recording.
     * A recorder that keeps no such buffer returns empty — the partials loop then simply
     * publishes nothing (graceful degradation), and recording is unaffected either way.
     */
    fun snapshotRecentSamples(): FloatArray = FloatArray(0)

    /**
     * The open segment still buffered when recording stops — the remainder after the last
     * committed segment — for the final committed decode. Null when not segmenting or empty.
     */
    fun flushOpenSegment(): ClosedSegment? = null
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

    /**
     * Whether this engine can decode raw samples for live tail-window partials (#42),
     * mirroring the desktop's `supports_partials`. Defaults false so any engine that
     * doesn't implement partials degrades to no-preview without a wiring change.
     */
    val supportsPartials: Boolean get() = false

    /**
     * Decode raw normalised float samples ([-1, 1], 16 kHz mono) to text, for the live
     * preview. Returns null when no partial is produced — the engine was busy with a
     * committed decode, or partials are unsupported. MUST NOT disturb a committed decode
     * or the recording. Defaults to null (no partials).
     */
    suspend fun transcribeSamples(samples: FloatArray): String? = null

    /**
     * Decode raw samples on the **committed** path — the rolling transcript's segments
     * (issue: rolling-committed transcript). Unlike [transcribeSamples] this WAITS for the
     * engine (it is durable product, never a skip), serialised behind any in-flight decode
     * through the same gate, so segments commit in order and a live partial yields to them.
     * Returns null only when no model is available. Defaults to null (no engine).
     */
    suspend fun transcribeSamplesCommitted(samples: FloatArray): Transcript? = null
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

    /** Notes left mid-recording by a process death, recovered on next start. */
    suspend fun recordingNotes(): List<Note>

    /** Append one committed segment of a note's rolling transcript (written as it lands). */
    suspend fun addSegment(segment: NoteSegment): Long

    /** A note's committed segments, ordered — the source of truth its transcript concatenates. */
    suspend fun segmentsFor(noteId: Long): List<NoteSegment>

    /**
     * Full-text search over transcripts (issue #40). [query] is raw user text; the
     * implementation turns it into a safe FTS match. Notes without a transcript are
     * naturally absent from the results. Ordered newest-first.
     */
    fun search(query: String): Flow<List<Note>>
}
