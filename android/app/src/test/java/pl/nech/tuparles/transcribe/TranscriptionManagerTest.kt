package pl.nech.tuparles.transcribe

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import pl.nech.tuparles.core.Transcript
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.ui.FakeNotesRepository

/** Configurable stand-in for the native whisper engine. */
private class FakeEngine(
    override val available: Boolean,
    private val result: (String) -> Transcript = { Transcript("bonjour world", "fr", "ggml-base") },
) : TranscriptionEngine {
    var calls = 0
    override suspend fun transcribe(wavPath: String): Transcript {
        calls++
        return result(wavPath)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class TranscriptionManagerTest {

    private fun note(id: Long, state: TranscriptState = TranscriptState.PENDING) =
        Note(id = id, wavPath = "/tmp/note_$id.wav", createdAt = id, durationS = 2f, transcriptState = state)

    private fun manager(engine: TranscriptionEngine, repo: FakeNotesRepository, scope: CoroutineScope) =
        TranscriptionManager(engine, repo, scope)

    @Test
    fun decodes_and_stores_transcript_when_engine_available() = runTest {
        val repo = FakeNotesRepository()
        repo.emit(listOf(note(1)))
        val engine = FakeEngine(available = true)
        val mgr = manager(engine, repo, this)

        mgr.process(1)

        val out = repo.get(1)!!
        assertEquals("bonjour world", out.transcript)
        assertEquals("fr", out.transcriptLang)
        assertEquals(TranscriptState.DONE, out.transcriptState)
        assertEquals(1, engine.calls)
    }

    @Test
    fun marks_unavailable_and_never_calls_engine_when_no_model() = runTest {
        val repo = FakeNotesRepository()
        repo.emit(listOf(note(1)))
        val engine = FakeEngine(available = false)
        val mgr = manager(engine, repo, this)

        mgr.process(1)

        val out = repo.get(1)!!
        assertEquals(TranscriptState.UNAVAILABLE, out.transcriptState)
        assertNull(out.transcript)
        assertEquals(0, engine.calls) // graceful degrade: engine untouched
    }

    @Test
    fun marks_failed_but_keeps_audio_when_decode_throws() = runTest {
        val repo = FakeNotesRepository()
        repo.emit(listOf(note(1)))
        val engine = FakeEngine(available = true) { error("boom") }
        val mgr = manager(engine, repo, this)

        mgr.process(1)

        val out = repo.get(1)!!
        assertEquals(TranscriptState.FAILED, out.transcriptState)
        assertNull(out.transcript)
        assertEquals("/tmp/note_1.wav", out.wavPath) // audio path untouched
    }

    @Test
    fun already_done_note_is_left_alone() = runTest {
        val repo = FakeNotesRepository()
        repo.emit(listOf(note(1, TranscriptState.DONE).copy(transcript = "kept")))
        val engine = FakeEngine(available = true)
        val mgr = manager(engine, repo, this)

        mgr.process(1)

        assertEquals("kept", repo.get(1)!!.transcript)
        assertEquals(0, engine.calls) // idempotent, no re-decode
    }

    @Test
    fun missing_note_is_a_noop() = runTest {
        val repo = FakeNotesRepository()
        val engine = FakeEngine(available = true)
        manager(engine, repo, this).process(42)
        assertEquals(0, engine.calls)
    }

    @Test
    fun resume_pending_reprocesses_interrupted_notes() = runTest {
        val repo = FakeNotesRepository()
        repo.emit(
            listOf(
                note(1, TranscriptState.PENDING),
                note(2, TranscriptState.RUNNING), // interrupted mid-decode by a prior process
                note(3, TranscriptState.DONE).copy(transcript = "done"),
            ),
        )
        val engine = FakeEngine(available = true)
        val scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler))
        val mgr = manager(engine, repo, scope)

        mgr.resumePending()

        assertEquals(TranscriptState.DONE, repo.get(1)!!.transcriptState)
        assertEquals(TranscriptState.DONE, repo.get(2)!!.transcriptState)
        assertEquals(2, engine.calls) // note 3 (already DONE) not re-decoded
    }
}
