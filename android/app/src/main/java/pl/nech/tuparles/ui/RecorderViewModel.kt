package pl.nech.tuparles.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecorderStateHolder
import javax.inject.Inject

/** Everything a screen renders: the live recorder state + the saved notes. */
data class UiState(
    val recorder: RecorderState = RecorderState.Idle,
    val notes: List<Note> = emptyList(),
) {
    val isRecording: Boolean get() = recorder is RecorderState.Recording
    val isBusy: Boolean get() = recorder is RecorderState.Recording || recorder is RecorderState.Saving
}

@HiltViewModel
class RecorderViewModel @Inject constructor(
    private val notes: NotesRepository,
    stateHolder: RecorderStateHolder,
) : ViewModel() {

    val uiState: StateFlow<UiState> =
        combine(stateHolder.state, notes.observeNotes()) { recorder, list ->
            UiState(recorder = recorder, notes = list)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), UiState())

    fun delete(note: Note) {
        viewModelScope.launch { notes.delete(note) }
    }
}
