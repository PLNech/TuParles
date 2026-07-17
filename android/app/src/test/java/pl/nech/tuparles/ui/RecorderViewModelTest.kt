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
