package pl.nech.tuparles.record

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/** What every surface renders. Process-scoped, so it outlives any one screen. */
sealed interface RecorderState {
    data object Idle : RecorderState
    data class Recording(val elapsedMs: Long, val level: Float) : RecorderState
    data object Saving : RecorderState
}

/**
 * The single source of truth for recording state, shared (as a Hilt singleton)
 * between the [RecordingService] that owns the mic and the ViewModel that renders
 * it. Decoupled from the Service class so it is trivially unit-testable — no global
 * statics, no Android on the read path.
 */
@Singleton
class RecorderStateHolder @Inject constructor() {
    private val _state = MutableStateFlow<RecorderState>(RecorderState.Idle)
    val state: StateFlow<RecorderState> = _state.asStateFlow()

    fun set(state: RecorderState) {
        _state.value = state
    }
}
