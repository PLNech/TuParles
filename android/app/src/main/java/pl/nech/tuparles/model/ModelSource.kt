package pl.nech.tuparles.model

/**
 * Where the engine loads its weights from right now. Two shapes, mirroring the two
 * whisper.cpp loaders: a real file in app-private storage (downloaded or dev-pushed),
 * or a bundled APK asset (a dev build that chose to ship one). [displayName] is the
 * model provenance stamped on a decoded transcript.
 */
sealed interface ModelSource {
    val displayName: String

    /** A GGML file in app-private storage (`filesDir/models/…`). */
    data class DownloadedFile(val path: String, override val displayName: String) : ModelSource

    /** A GGML file packaged as an uncompressed APK asset (dev builds only). */
    data class BundledAsset(val assetPath: String, override val displayName: String) : ModelSource
}

/**
 * The seam the engine reads to find the current model. Implemented by the model
 * manager (which owns the active selection + the downloaded set). Kept tiny so the
 * engine has no back-reference to the manager (no Hilt dependency cycle): the engine
 * simply asks "what should I load?" each time it needs a context.
 */
interface ModelResolver {
    /** The model to load now, or null when none is available (record-only mode). */
    fun current(): ModelSource?

    /** True iff [current] would return non-null. Cheap; safe to call per note. */
    fun hasModel(): Boolean = current() != null
}
