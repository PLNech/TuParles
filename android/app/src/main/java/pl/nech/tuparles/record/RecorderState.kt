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

    /**
     * Recording stopped; the note is being written and transcribed. This is NOT "recording"
     * — the mic is released — so the UI must say "transcription…", never "enregistrement…".
     * [remaining] is the live-decode backlog still to commit (0 when nothing is queued or the
     * rolling path was not armed). The honest post-stop state (device validation, #13).
     */
    data class Transcribing(val remaining: Int = 0) : RecorderState
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

    /**
     * The live tail-window preview text (#42): the transcription of the last few seconds
     * of audio while recording. Deliberately a separate flow from [state] so the ~5 s
     * partial loop and the high-frequency level meter never clobber each other's writes.
     * Null when not recording (or before the first window decodes).
     */
    private val _partial = MutableStateFlow<String?>(null)
    val partial: StateFlow<String?> = _partial.asStateFlow()

    /**
     * The rolling *committed* transcript while recording (the record-minutes-and-pray fix):
     * the concatenation of segments already decoded and persisted, shown as settled
     * (non-italic) text, with [partial] as the dim italic tail after it. What you see here is
     * what you keep. Its own flow — separate from the high-frequency level meter and the
     * ~5 s partial — so none of the three clobber each other. Null when nothing is committed.
     */
    private val _committed = MutableStateFlow<String?>(null)
    val committed: StateFlow<String?> = _committed.asStateFlow()

    /**
     * True while recording with the rolling transcript wanted (toggle on, model loaded) but
     * the active model too slow for it — so we degraded to a post-stop decode and the UI
     * shows a one-line hint. A separate flow, like the others, so nothing clobbers it.
     */
    private val _liveDegraded = MutableStateFlow(false)
    val liveDegraded: StateFlow<Boolean> = _liveDegraded.asStateFlow()

    fun set(state: RecorderState) {
        // Any non-recording state ends the live previews; no stale text survives into
        // Transcribing/Idle. The degrade hint is a recording-only cue, so it clears too.
        if (state !is RecorderState.Recording) {
            _partial.value = null
            _committed.value = null
            _liveDegraded.value = false
        }
        _state.value = state
    }

    /** Flag (or clear) the "model too slow for the live transcript" degrade hint. */
    fun setLiveDegraded(degraded: Boolean) {
        _liveDegraded.value = degraded
    }

    fun setPartial(text: String) {
        _partial.value = text
    }

    fun clearPartial() {
        _partial.value = null
    }

    /** Publish the growing committed transcript (settled text) as a segment lands. */
    fun setCommitted(text: String) {
        _committed.value = text
    }

    fun clearCommitted() {
        _committed.value = null
    }
}
