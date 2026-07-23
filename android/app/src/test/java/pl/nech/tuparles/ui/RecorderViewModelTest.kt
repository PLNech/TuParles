package pl.nech.tuparles.ui

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecorderStateHolder

@OptIn(ExperimentalCoroutinesApi::class)
class RecorderViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun note(id: Long) = Note(id = id, wavPath = "/tmp/note_$id.wav", createdAt = id, durationS = 2f)

    private fun noteT(id: Long, transcript: String?) =
        Note(id = id, wavPath = "/tmp/note_$id.wav", createdAt = id, durationS = 2f, transcript = transcript)

    @Test
    fun uiState_starts_idle_and_empty() = runTest(dispatcher) {
        val vm = RecorderViewModel(FakeNotesRepository(), RecorderStateHolder())
        assertEquals(RecorderState.Idle, vm.uiState.value.recorder)
        assertTrue(vm.uiState.value.notes.isEmpty())
        assertFalse(vm.uiState.value.isRecording)
    }

    @Test
    fun uiState_combines_notes_and_recorder_state() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val holder = RecorderStateHolder()
        val vm = RecorderViewModel(repo, holder)

        // A subscriber is required for the WhileSubscribed stateIn to run upstream.
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        repo.emit(listOf(note(1), note(2)))
        holder.set(RecorderState.Recording(1_000L, 0.5f))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(2, state.notes.size)
        assertTrue(state.isRecording)
        assertTrue(state.isBusy)
    }

    @Test
    fun search_filters_to_matching_transcripts_and_counts_untranscribed() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val vm = RecorderViewModel(repo, RecorderStateHolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        repo.emit(
            listOf(
                noteT(1, "bonjour le monde"),
                noteT(2, "hello world"),
                noteT(3, null), // never transcribed
            ),
        )
        advanceUntilIdle()

        // No query: the whole list, not in search mode.
        assertEquals(3, vm.uiState.value.notes.size)
        assertFalse(vm.uiState.value.searching)
        assertEquals(0, vm.uiState.value.untranscribedHidden)

        vm.onQueryChange("bonjour")
        advanceUntilIdle()

        val s = vm.uiState.value
        assertTrue(s.searching)
        assertEquals(listOf(1L), s.notes.map { it.id })
        // Note 3 has no transcript, so it can't appear — surface that as a hint.
        assertEquals(1, s.untranscribedHidden)
    }

    @Test
    fun search_matches_prefix_as_you_type() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val vm = RecorderViewModel(repo, RecorderStateHolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()
        repo.emit(listOf(noteT(1, "bonjour le monde"), noteT(2, "hello world")))
        advanceUntilIdle()

        vm.onQueryChange("bon") // prefix of "bonjour"
        advanceUntilIdle()

        assertEquals(listOf(1L), vm.uiState.value.notes.map { it.id })
    }

    @Test
    fun clearing_query_restores_the_full_list() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val vm = RecorderViewModel(repo, RecorderStateHolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()
        repo.emit(listOf(noteT(1, "bonjour"), noteT(2, "hello")))
        advanceUntilIdle()

        vm.onQueryChange("bonjour")
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.notes.size)

        vm.onQueryChange("")
        advanceUntilIdle()
        assertFalse(vm.uiState.value.searching)
        assertEquals(2, vm.uiState.value.notes.size)
    }

    @Test
    fun no_match_yields_empty_results_still_in_search_mode() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val vm = RecorderViewModel(repo, RecorderStateHolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()
        repo.emit(listOf(noteT(1, "bonjour"), noteT(2, "hello")))
        advanceUntilIdle()

        vm.onQueryChange("zzz")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.searching)
        assertTrue(vm.uiState.value.notes.isEmpty())
    }

    @Test
    fun query_echoes_synchronously_while_search_stays_debounced() = runTest(dispatcher) {
        // Regression for #41: the text field must echo each keystroke immediately, so the display
        // query updates synchronously with onQueryChange; only the search execution is debounced.
        val repo = FakeNotesRepository()
        val vm = RecorderViewModel(repo, RecorderStateHolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()
        repo.emit(listOf(noteT(1, "bonjour le monde"), noteT(2, "hello world")))
        advanceUntilIdle()

        vm.onQueryChange("bonjour")
        // Display echoes instantly — no scheduler advance, no debounce.
        assertEquals("bonjour", vm.queryText.value)
        // The search itself has not run yet: still the full, unfiltered list.
        assertFalse(vm.uiState.value.searching)
        assertEquals(2, vm.uiState.value.notes.size)

        // Only after the debounce window does the filtered result land.
        advanceUntilIdle()
        assertTrue(vm.uiState.value.searching)
        assertEquals(listOf(1L), vm.uiState.value.notes.map { it.id })
    }

    @Test
    fun partial_preview_text_flows_into_uiState() = runTest(dispatcher) {
        // #42: the live tail-window preview is a separate holder flow; it must surface in UiState.
        val holder = RecorderStateHolder()
        val vm = RecorderViewModel(FakeNotesRepository(), holder)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        holder.set(RecorderState.Recording(1_000L, 0.5f))
        holder.setPartial("bonjour le")
        advanceUntilIdle()
        assertEquals("bonjour le", vm.uiState.value.partial)

        // Leaving the recording state clears the preview (no stale partial into Transcribing/Idle).
        holder.set(RecorderState.Transcribing())
        advanceUntilIdle()
        assertEquals(null, vm.uiState.value.partial)
    }

    @Test
    fun committed_and_partial_transcript_flow_into_uiState() = runTest(dispatcher) {
        // The rolling transcript surfaces the settled (committed) text and the live tail
        // separately, so the screen can render "what you keep" upright and the preview italic.
        val holder = RecorderStateHolder()
        val vm = RecorderViewModel(FakeNotesRepository(), holder)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        holder.set(RecorderState.Recording(1_000L, 0.5f))
        holder.setCommitted("bonjour le monde")
        holder.setPartial("et voici")
        advanceUntilIdle()
        assertEquals("bonjour le monde", vm.uiState.value.committed)
        assertEquals("et voici", vm.uiState.value.partial)

        // Leaving the recording state clears both the settled text and the preview.
        holder.set(RecorderState.Transcribing())
        advanceUntilIdle()
        assertEquals(null, vm.uiState.value.committed)
        assertEquals(null, vm.uiState.value.partial)
    }

    @Test
    fun post_stop_is_a_transcribing_state_busy_but_not_recording_with_the_backlog_count() = runTest(dispatcher) {
        val holder = RecorderStateHolder()
        val vm = RecorderViewModel(FakeNotesRepository(), holder)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        holder.set(RecorderState.Transcribing(remaining = 3))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse("transcribing is NOT recording (the mic is released)", state.isRecording)
        assertTrue("but the UI is busy (button disabled, honest 'transcription…')", state.isBusy)
        assertEquals(RecorderState.Transcribing(3), state.recorder)
    }

    @Test
    fun the_slow_model_degrade_hint_flows_into_uiState() = runTest(dispatcher) {
        val holder = RecorderStateHolder()
        val vm = RecorderViewModel(FakeNotesRepository(), holder)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        holder.set(RecorderState.Recording(0L, 0f))
        holder.setLiveDegraded(true)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.liveDegraded)

        // Cleared when recording ends.
        holder.set(RecorderState.Transcribing())
        advanceUntilIdle()
        assertFalse(vm.uiState.value.liveDegraded)
    }

    @Test
    fun delete_forwards_to_repository() = runTest(dispatcher) {
        val repo = FakeNotesRepository()
        val target = note(7)
        repo.emit(listOf(target))
        val vm = RecorderViewModel(repo, RecorderStateHolder())

        vm.delete(target)
        advanceUntilIdle()

        assertTrue(repo.deleted.contains(target))
    }
}
