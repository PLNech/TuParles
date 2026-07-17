package pl.nech.tuparles.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.data.FtsQuery
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecorderStateHolder
import javax.inject.Inject

/**
 * Everything a screen renders: the live recorder state + the notes to show.
 *
 * When [searching] is true the list is a full-text search result over transcripts;
 * [untranscribedHidden] is how many notes carry no transcript and so can't appear in
 * text search — surfaced to the user as a hint (a visible limitation over a silent one).
 */
data class UiState(
    val recorder: RecorderState = RecorderState.Idle,
    val notes: List<Note> = emptyList(),
    val query: String = "",
    val searching: Boolean = false,
    val untranscribedHidden: Int = 0,
    /** Live tail-window preview text while recording (#42); null when idle or not yet decoded. */
    val partial: String? = null,
) {
    val isRecording: Boolean get() = recorder is RecorderState.Recording
    val isBusy: Boolean get() = recorder is RecorderState.Recording || recorder is RecorderState.Saving
}

@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class RecorderViewModel @Inject constructor(
    private val notes: NotesRepository,
    stateHolder: RecorderStateHolder,
) : ViewModel() {

    private val query = MutableStateFlow("")

    /**
     * The live, undebounced query for the text field to echo. A Compose TextField must be driven
     * by state that updates synchronously with each keystroke; binding it to the debounced
     * search round-trip below would reset the field to a stale value on every recomposition and
     * swallow input (#41). Search execution keeps the debounce; display does not.
     */
    val queryText: StateFlow<String> = query.asStateFlow()

    /** Either the full list (empty/punctuation-only query) or the search hits, with the hint count. */
    private val notesView =
        query
            .debounce { if (it.isBlank()) 0L else SEARCH_DEBOUNCE_MS }
            .distinctUntilChanged()
            .flatMapLatest { raw ->
                if (FtsQuery.toMatch(raw) == null) {
                    // Nothing searchable: show every note, no hint.
                    combine(notes.observeNotes(), MutableStateFlow(raw)) { all, q ->
                        NotesView(notes = all, query = q, searching = false, untranscribedHidden = 0)
                    }
                } else {
                    // Search hits + how many notes were excluded for lacking a transcript.
                    combine(notes.observeNotes(), notes.search(raw)) { all, hits ->
                        NotesView(
                            notes = hits,
                            query = raw,
                            searching = true,
                            untranscribedHidden = all.count { it.transcript.isNullOrBlank() },
                        )
                    }
                }
            }

    val uiState: StateFlow<UiState> =
        combine(stateHolder.state, notesView, stateHolder.partial) { recorder, view, partial ->
            UiState(
                recorder = recorder,
                notes = view.notes,
                query = view.query,
                searching = view.searching,
                untranscribedHidden = view.untranscribedHidden,
                partial = partial,
            )
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), UiState())

    fun onQueryChange(raw: String) {
        query.value = raw
    }

    fun delete(note: Note) {
        viewModelScope.launch { notes.delete(note) }
    }

    private data class NotesView(
        val notes: List<Note>,
        val query: String,
        val searching: Boolean,
        val untranscribedHidden: Int,
    )

    private companion object {
        const val SEARCH_DEBOUNCE_MS = 250L
    }
}
