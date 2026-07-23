package pl.nech.tuparles.model

/**
 * The one thing the model manager needs from transcription: "a model just landed —
 * decode whatever was waiting for it." Declared here (the consumer's side) so the model
 * package does not depend on the transcription package, and injected into the manager
 * lazily to break the otherwise-circular Hilt graph
 * (engine → resolver → manager → pending-work → transcription-manager → engine).
 */
interface PendingWork {
    /** Re-enqueue notes left PENDING while no model was available. */
    fun retryPending()
}
