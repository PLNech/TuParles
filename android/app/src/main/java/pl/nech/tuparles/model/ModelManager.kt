package pl.nech.tuparles.model

import android.util.Log
import dagger.Lazy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Owns the download-picker world: which models are on disk, which one is active, and any
 * download in flight. It is also the engine's [ModelResolver] — the single source of
 * truth for "what should we load?" — so the engine keeps no back-reference to it.
 *
 * Download coordination lives here in pure Kotlin (poll the [FileDownloader], publish
 * progress, verify sha256 before activating, atomic-install, then wake pending notes),
 * with Android's `DownloadManager` behind the [downloader] abstraction. That keeps the
 * whole state machine unit-testable on the JVM with a fake downloader + a temp-dir store.
 *
 * The safety invariant, structural not statistical: a downloaded model is *never*
 * activated until its bytes hash to the catalog's sha256 (see [ModelStore.install]).
 */
class ModelManager(
    private val store: ModelStore,
    private val downloader: FileDownloader,
    private val prefs: ModelPreferences,
    private val scope: CoroutineScope,
    private val bundledAssetPresent: Boolean,
    private val pending: Lazy<PendingWork>,
    private val pollIntervalMs: Long = DEFAULT_POLL_MS,
) : ModelResolver {

    private val _downloads = MutableStateFlow<Map<String, ModelDownloadState>>(emptyMap())
    /** Per-model download state, keyed by [ModelSpec.id]. Absent key ⇒ [ModelDownloadState.Idle]. */
    val downloads: StateFlow<Map<String, ModelDownloadState>> = _downloads.asStateFlow()

    private val _installedIds = MutableStateFlow(store.installedIds())
    /** Ids of models with a verified file on disk. */
    val installedIds: StateFlow<Set<String>> = _installedIds.asStateFlow()

    private val _activeId = MutableStateFlow(prefs.activeModelId)
    /** The user's active choice, or null (⇒ resolution uses recommended / any installed). */
    val activeId: StateFlow<String?> = _activeId.asStateFlow()

    /** Whether this build shipped a dev asset (a lean release APK ships none). */
    val hasBundledAsset: Boolean get() = bundledAssetPresent

    private val jobs = mutableMapOf<String, Job>()
    private val handles = mutableMapOf<String, Long>()

    // ---- ModelResolver (read by the engine) --------------------------------------------

    override fun current(): ModelSource? =
        when (val choice = ModelResolution.resolve(prefs.activeModelId, store.installedIds(), bundledAssetPresent)) {
            is ModelResolution.Choice.Downloaded ->
                ModelSource.DownloadedFile(
                    path = store.fileFor(choice.spec).absolutePath,
                    displayName = choice.spec.fileName.removeSuffix(".bin"),
                )
            ModelResolution.Choice.Bundled ->
                ModelSource.BundledAsset(ModelCatalog.BUNDLED_ASSET_PATH, ModelCatalog.BUNDLED_ASSET_NAME)
            null -> null
        }

    // ---- Actions -----------------------------------------------------------------------

    /** Total bytes used by downloaded models (for the Réglages storage line). */
    fun totalBytesUsed(): Long = store.totalBytesUsed()

    /** Pick the active model. The engine reloads to it on its next decode. */
    fun select(spec: ModelSpec) {
        prefs.activeModelId = spec.id
        _activeId.value = spec.id
    }

    /** Remove a model's file; if it was active, clear the selection (resolution falls back). */
    fun delete(spec: ModelSpec) {
        store.delete(spec)
        if (prefs.activeModelId == spec.id) {
            prefs.activeModelId = null
            _activeId.value = null
        }
        refreshInstalled()
        setState(spec.id, ModelDownloadState.Idle)
    }

    /** Cancel an in-flight download and drop its partial bytes. */
    fun cancel(spec: ModelSpec) {
        jobs.remove(spec.id)?.cancel()
        handles.remove(spec.id)?.let(downloader::cancel)
        setState(spec.id, ModelDownloadState.Failed(FailReason.CANCELLED))
    }

    /**
     * Start (or restart) a download. [allowMetered] is the user's explicit decision after
     * being shown the size — we never silently pull hundreds of MB over cellular.
     */
    fun startDownload(spec: ModelSpec, allowMetered: Boolean) {
        if (store.isInstalled(spec)) {
            setState(spec.id, ModelDownloadState.Ready)
            return
        }
        jobs.remove(spec.id)?.cancel()
        setState(spec.id, ModelDownloadState.Downloading(0L, spec.sizeBytes))
        val job = scope.launch {
            runDownload(spec, allowMetered)
        }
        jobs[spec.id] = job
    }

    private suspend fun runDownload(spec: ModelSpec, allowMetered: Boolean) {
        val handle = runCatching { downloader.enqueue(spec.url, spec.label, allowMetered) }
            .getOrElse {
                Log.w(TAG, "enqueue failed for ${spec.id}", it)
                setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                return
            }
        handles[spec.id] = handle

        while (true) {
            val status = runCatching { downloader.status(handle) }.getOrElse {
                setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                return
            }
            when (status.state) {
                RawDownloadState.PENDING, RawDownloadState.RUNNING -> {
                    val total = if (status.totalBytes > 0L) status.totalBytes else spec.sizeBytes
                    setState(spec.id, ModelDownloadState.Downloading(status.bytesSoFar, total))
                    delay(pollIntervalMs)
                }
                RawDownloadState.FAILED -> {
                    downloader.cancel(handle)
                    handles.remove(spec.id)
                    setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                    return
                }
                RawDownloadState.SUCCESS -> break
            }
        }

        setState(spec.id, ModelDownloadState.Verifying)
        val staged = downloader.stagedFile(handle)
        if (staged == null) {
            downloader.cancel(handle)
            handles.remove(spec.id)
            setState(spec.id, ModelDownloadState.Failed(FailReason.STORAGE))
            return
        }

        val result = store.install(staged, spec)
        downloader.cancel(handle) // clear the DownloadManager record + its staging copy
        handles.remove(spec.id)

        when (result) {
            ModelStore.InstallResult.OK -> {
                refreshInstalled()
                setState(spec.id, ModelDownloadState.Ready)
                // A model just landed: decode anything that was waiting for one.
                runCatching { pending.get().retryPending() }
                    .onFailure { Log.w(TAG, "retryPending failed", it) }
            }
            ModelStore.InstallResult.CHECKSUM_MISMATCH, ModelStore.InstallResult.SIZE_MISMATCH ->
                setState(spec.id, ModelDownloadState.Failed(FailReason.CHECKSUM))
            ModelStore.InstallResult.STORAGE_ERROR, ModelStore.InstallResult.MISSING ->
                setState(spec.id, ModelDownloadState.Failed(FailReason.STORAGE))
        }
    }

    private fun refreshInstalled() {
        _installedIds.value = store.installedIds()
    }

    private fun setState(id: String, state: ModelDownloadState) {
        _downloads.value = _downloads.value.toMutableMap().apply { put(id, state) }
    }

    private companion object {
        const val TAG = "TuParles"
        const val DEFAULT_POLL_MS = 400L
    }
}
