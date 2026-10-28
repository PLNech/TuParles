package pl.nech.tuparles.record

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.NoteSegment
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.ui.FakeNotesRepository
import java.io.File

/**
 * The destroy-while-recording case: a row left in RECORDING is invisible, so
 * salvage must leave one the list can show, or delete an empty instant-stop.
 */
class TakeSalvageTest {

    @Test
    fun destroy_with_audio_on_disk_leaves_a_visible_pending_row() = runTest {
        val repo = FakeNotesRepository()
        val wav = File.createTempFile("salvage", ".wav")
        writeWav(wav, ShortArray(SAMPLE_RATE) { 1000 })
        val id = repo.add(recording(wav))

        val path = salvageInterruptedTake(repo, id, wav, pcmSamples = 0)

        val note = repo.get(id)!!
        assertEquals("destroyed-while-recording", path)
        assertEquals(TranscriptState.PENDING, note.transcriptState)
        assertEquals(1f, note.durationS, 0.01f)
        assertTrue(repo.visibleNow().any { it.id == id })
        wav.delete()
    }

    @Test
    fun destroy_with_committed_text_keeps_that_text_and_shows_the_row() = runTest {
        val repo = FakeNotesRepository()
        val wav = File.createTempFile("salvage", ".wav")
        writeWav(wav, ShortArray(SAMPLE_RATE) { 1000 })
        val id = repo.add(recording(wav))
        repo.addSegment(NoteSegment(noteId = id, segmentIndex = 0, text = "bonjour", startSample = 0, endSample = 8000))

        salvageInterruptedTake(repo, id, wav, pcmSamples = SAMPLE_RATE)

        val note = repo.get(id)!!
        assertEquals(TranscriptState.DONE, note.transcriptState)
        assertEquals("bonjour", note.transcript)
        assertTrue(repo.visibleNow().any { it.id == id })
        wav.delete()
    }

    @Test
    fun destroy_with_samples_only_in_ram_is_a_visible_failure() = runTest {
        val repo = FakeNotesRepository()
        val wav = File.createTempFile("salvage-empty", ".wav")
        GrowingWav(wav).close() // header, no samples — the file exists, the audio does not
        val id = repo.add(recording(wav))

        salvageInterruptedTake(repo, id, wav, pcmSamples = SAMPLE_RATE)

        val note = repo.get(id)!!
        assertEquals(TranscriptState.FAILED, note.transcriptState)
        assertNull(note.transcript)
        assertTrue(repo.visibleNow().any { it.id == id })
        wav.delete()
    }

    @Test
    fun instant_stop_drops_the_empty_note_and_the_spill_file() = runTest {
        val repo = FakeNotesRepository()
        val wav = File.createTempFile("salvage-none", ".wav")
        GrowingWav(wav).close()
        val id = repo.add(recording(wav))

        val path = salvageInterruptedTake(repo, id, wav, pcmSamples = 0)

        assertEquals("dropped-empty", path)
        assertNull(repo.get(id))
        assertFalse(wav.exists())
    }

    @Test
    fun post_hoc_destroy_with_no_row_yet_creates_a_visible_one() = runTest {
        val repo = FakeNotesRepository()
        val wav = File.createTempFile("salvage-posthoc", ".wav")
        writeWav(wav, ShortArray(SAMPLE_RATE * 2) { 500 })
        val queued = mutableListOf<Long>()

        val path = salvageInterruptedTake(repo, noteId = 0, wav, pcmSamples = 0) { queued += it }

        assertEquals("destroyed-while-recording", path)
        val visible = repo.visibleNow()
        assertEquals(1, visible.size)
        assertEquals(TranscriptState.PENDING, visible.single().transcriptState)
        assertEquals(listOf(visible.single().id), queued)
        wav.delete()
    }

    private fun recording(wav: File) = Note(
        id = 7,
        wavPath = wav.absolutePath,
        createdAt = 7,
        durationS = 0f,
        transcriptState = TranscriptState.RECORDING,
    )
}
