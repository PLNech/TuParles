package pl.nech.tuparles.model

/**
 * The per-model download lifecycle, surfaced to the UI as a StateFlow. A model is
 * either not on disk (see [Idle]) or its bytes are in flight; once verified and moved
 * into place it becomes installed (tracked separately, not a state here) — [Ready] is
 * the transient "just landed" beat before the installed-set updates.
 */
sealed interface ModelDownloadState {

    /** No download in flight for this model. */
    data object Idle : ModelDownloadState

    /** Bytes in flight. [totalBytes] may be 0 briefly before the server reports length. */
    data class Downloading(val bytesSoFar: Long, val totalBytes: Long) : ModelDownloadState {
        /** 0f..1f, or 0f while the total is still unknown. */
        val fraction: Float
            get() = if (totalBytes > 0L) (bytesSoFar.toFloat() / totalBytes).coerceIn(0f, 1f) else 0f
    }

    /** Bytes are down; hashing before activation (the safety gate). */
    data object Verifying : ModelDownloadState

    /** Verified and moved into app-private storage. The model is now usable. */
    data object Ready : ModelDownloadState

    /** The download did not produce a usable model; [reason] is user-actionable. */
    data class Failed(val reason: FailReason) : ModelDownloadState
}

/** Why a download failed, kept coarse and honest (no leaking of internals to the UI). */
enum class FailReason {
    /** Connection dropped / server error / DownloadManager reported failure. */
    NETWORK,

    /** The bytes arrived but the sha256 did not match the catalog — never activated. */
    CHECKSUM,

    /** Could not write to app-private storage (out of space, permissions). */
    STORAGE,

    /** The user cancelled. */
    CANCELLED,

    /** Anything else. */
    UNKNOWN,
}
