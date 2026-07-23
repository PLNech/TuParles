package pl.nech.tuparles.transcribe

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import pl.nech.tuparles.core.Transcript
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.record.ClosedSegment
import pl.nech.tuparles.record.RecorderPreferences
import pl.nech.tuparles.record.RecorderStateHolder
import pl.nech.tuparles.record.SAMPLE_RATE
import pl.nech.tuparles.record.writeWav
import pl.nech.tuparles.ui.FakeNotesRepository
import java.io.File

/**
 * The rolling committed transcript state machine: progressive commit + persistence,
 * the never-replace-committed doctrine, the finalisation-decodes-only-the-remainder rule,
 * the no-dupes / no-loss reconciliation matrix, and process-death recovery. Fake engine +
 * in-memory repo + real state holder; deterministic, no device.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RollingTranscriberTest {

    /** Length-1 marker arrays decode to "w<index>"; longer arrays (WAV slices) to "rem". */
    private class FakeEngine(
        override val available: Boolean = true,
        private val decode: (FloatArray) -> String? = { s -> if (s.size == 1) "w${s[0].toInt()}" else "rem" },
    ) : TranscriptionEngine {
        var committedCalls = 0
        override suspend fun transcribe(wavPath: String): Transcript = error("unused in rolling tests")
        override suspend fun transcribeSamplesCommitted(samples: FloatArray): Transcript? {
            if (!available || samples.isEmpty()) return null
            committedCalls++
            return decode(samples)?.let { Transcript(it, null, "fake") }
        }
    }

    private class FakePrefs(override var rollingTranscriptEnabled: Boolean = true) : RecorderPreferences

    /** A closed segment whose marker sample encodes its index (so decode is order-checkable). */
    private fun seg(index: Int, start: Int, end: Int) =
        ClosedSegment(index, start, end, floatArrayOf(index.toFloat()))

    private fun recordingNote(id: Long, wavPath: String = "/notes/note_$id.wav") =
        Note(id = id, wavPath = wavPath, createdAt = id, durationS = 0f, transcriptState = TranscriptState.RECORDING)

    private fun rolling(
        engine: TranscriptionEngine,
        repo: FakeNotesRepository,
        holder: RecorderStateHolder,
        prefs: RecorderPreferences,
        scope: CoroutineScope,
    ) = RollingTranscriber(engine, repo, holder, prefs, scope)

    @Test
    fun should_arm_only_when_feature_on_and_model_available() {
        val repo = FakeNotesRepository()
        val holder = RecorderStateHolder()
        assertTrue(
            rolling(FakeEngine(available = true), repo, holder, FakePrefs(true), noopScope()).shouldArm(),
        )
        assertFalse(
            "off when the toggle is off",
            rolling(FakeEngine(available = true), repo, holder, FakePrefs(false), noopScope()).shouldArm(),
        )
        assertFalse(
            "off when no model is loaded (record-only degrade)",
            rolling(FakeEngine(available = false), repo, holder, FakePrefs(true), noopScope()).shouldArm(),
        )
    }

    @Test
    fun segments_commit_progressively_persist_and_publish() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1))
        val holder = RecorderStateHolder()
        holder.set(pl.nech.tuparles.record.RecorderState.Recording(0L, 0f))
        val engine = FakeEngine()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(engine, repo, holder, FakePrefs(), scope)

        rt.begin(1)
        rt.submit(seg(0, 0, SAMPLE_RATE))
        rt.submit(seg(1, SAMPLE_RATE, 2 * SAMPLE_RATE))
        advanceUntilIdle()

        // Persisted as they land, and the live committed text grows in order.
        assertEquals(2, repo.segmentsFor(1).size)
        assertEquals("w0 w1", holder.committed.value)
    }

    @Test
    fun finish_decodes_only_the_remainder_and_marks_done() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1))
        val holder = RecorderStateHolder()
        val engine = FakeEngine()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(engine, repo, holder, FakePrefs(), scope)

        rt.begin(1)
        rt.submit(seg(0, 0, SAMPLE_RATE))
        rt.submit(seg(1, SAMPLE_RATE, 2 * SAMPLE_RATE))
        advanceUntilIdle()
        val callsBeforeFinish = engine.committedCalls

        rt.finish(remainder = seg(2, 2 * SAMPLE_RATE, 3 * SAMPLE_RATE), durationS = 3f)

        // Exactly ONE more decode (the remainder) — never the whole take again.
        assertEquals(callsBeforeFinish + 1, engine.committedCalls)
        val note = repo.get(1)!!
        assertEquals("w0 w1 w2", note.transcript)
        assertEquals(TranscriptState.DONE, note.transcriptState)
        assertEquals(3f, note.durationS, 0.001f)
        assertNull("live committed cleared after finalisation", holder.committed.value)
    }

    @Test
    fun transcript_is_the_contiguous_concatenation_of_segments_no_dupes_no_loss() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1))
        val holder = RecorderStateHolder()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(FakeEngine(), repo, holder, FakePrefs(), scope)

        rt.begin(1)
        rt.submit(seg(0, 0, SAMPLE_RATE))
        rt.submit(seg(1, SAMPLE_RATE, 2 * SAMPLE_RATE))
        advanceUntilIdle()
        rt.finish(seg(2, 2 * SAMPLE_RATE, 3 * SAMPLE_RATE), durationS = 3f)

        val segs = repo.segmentsFor(1)
        // The stored transcript equals the ordered concatenation of the segment rows.
        assertEquals(segs.joinToString(" ") { it.text }, repo.get(1)!!.transcript)
        // Contiguous timeline: each segment's end is the next one's start — nothing lost, nothing doubled.
        for (k in 1 until segs.size) assertEquals(segs[k - 1].endSample, segs[k].startSample)
    }

    @Test
    fun a_failed_segment_decode_is_skipped_and_never_persisted() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1))
        val holder = RecorderStateHolder()
        // Segment index 1 throws; the others decode fine.
        val engine = FakeEngine(decode = { s -> if (s[0].toInt() == 1) error("boom") else "w${s[0].toInt()}" })
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(engine, repo, holder, FakePrefs(), scope)

        rt.begin(1)
        rt.submit(seg(0, 0, SAMPLE_RATE))
        rt.submit(seg(1, SAMPLE_RATE, 2 * SAMPLE_RATE)) // throws
        rt.submit(seg(2, 2 * SAMPLE_RATE, 3 * SAMPLE_RATE))
        advanceUntilIdle()
        rt.finish(null, durationS = 3f)

        // The failed segment left no row and no gap-filler; the rest survive in order.
        assertEquals(listOf("w0", "w2"), repo.segmentsFor(1).map { it.text })
        assertEquals("w0 w2", repo.get(1)!!.transcript)
        assertEquals(TranscriptState.DONE, repo.get(1)!!.transcriptState)
    }

    @Test
    fun cancel_abandons_the_session_without_finalising() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1))
        val holder = RecorderStateHolder()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(FakeEngine(), repo, holder, FakePrefs(), scope)

        rt.begin(1)
        rt.cancel()
        advanceUntilIdle()

        // The note is untouched by rolling (still RECORDING — the caller decides to delete it).
        assertEquals(TranscriptState.RECORDING, repo.get(1)!!.transcriptState)
        assertNull(holder.committed.value)
    }

    @Test
    fun recovery_rebuilds_transcript_from_committed_segments_when_wav_is_gone() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1, wavPath = "/does/not/exist.wav"))
        // Two segments were committed before the process died.
        repo.addSegment(pl.nech.tuparles.data.NoteSegment(noteId = 1, segmentIndex = 0, text = "bonjour", startSample = 0, endSample = SAMPLE_RATE.toLong()))
        repo.addSegment(pl.nech.tuparles.data.NoteSegment(noteId = 1, segmentIndex = 1, text = "le monde", startSample = SAMPLE_RATE.toLong(), endSample = 2L * SAMPLE_RATE))
        val holder = RecorderStateHolder()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(FakeEngine(), repo, holder, FakePrefs(), scope)

        rt.recover()
        advanceUntilIdle()

        val note = repo.get(1)!!
        assertEquals("bonjour le monde", note.transcript)
        assertEquals(TranscriptState.DONE, note.transcriptState)
        assertEquals(2f, note.durationS, 0.001f) // from the last committed segment's endSample
    }

    @Test
    fun recovery_of_an_empty_interrupted_recording_is_marked_failed() = runTest {
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1, wavPath = "/does/not/exist.wav")) // no segments, no audio
        val holder = RecorderStateHolder()
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(FakeEngine(), repo, holder, FakePrefs(), scope)

        rt.recover()
        advanceUntilIdle()

        val note = repo.get(1)!!
        assertNull(note.transcript)
        assertEquals(TranscriptState.FAILED, note.transcriptState)
    }

    @Test
    fun recovery_decodes_the_remainder_from_the_wav_when_it_reached_disk() = runTest {
        val wav = File.createTempFile("recover", ".wav").apply { deleteOnExit() }
        // 2 s of audio on disk; the first 1 s was already committed as a segment.
        writeWav(wav, ShortArray(2 * SAMPLE_RATE) { 4_000 })
        val repo = FakeNotesRepository()
        repo.add(recordingNote(1, wavPath = wav.absolutePath))
        repo.addSegment(pl.nech.tuparles.data.NoteSegment(noteId = 1, segmentIndex = 0, text = "committed", startSample = 0, endSample = SAMPLE_RATE.toLong()))
        val holder = RecorderStateHolder()
        val engine = FakeEngine() // longer arrays (the WAV remainder slice) decode to "rem"
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val rt = rolling(engine, repo, holder, FakePrefs(), scope)

        rt.recover()
        advanceUntilIdle()

        val note = repo.get(1)!!
        // Committed segment kept, remainder decoded post-hoc and appended — no re-decode of the head.
        assertEquals("committed rem", note.transcript)
        assertEquals(TranscriptState.DONE, note.transcriptState)
        assertEquals(2, repo.segmentsFor(1).size) // the recovered remainder was persisted too
    }

    private fun noopScope() = CoroutineScope(UnconfinedTestDispatcher())
}
