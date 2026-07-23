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
    // Fallback path for a stalled system download (Android 15 scheduler deferral, #13):
    // the direct in-app HTTP downloader. Defaults to the primary so existing call sites
    // and tests that never stall are unaffected.
    private val fallbackDownloader: FileDownloader = downloader,
    // Is the active network metered right now? Consulted only when deciding whether to
    // fall back while allowMetered=false — so we never force a metered transfer the user
    // declined. Injected (not ConnectivityManager directly) to keep this class pure.
    private val isMetered: () -> Boolean = { false },
    // Time source for the stall watchdog; injected so it is fake-clock testable.
    private val now: () -> Long = { System.currentTimeMillis() },
    private val stallThresholdMs: Long = DEFAULT_STALL_MS,
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
    // Which downloader currently owns each handle, so cancel() routes to the right one
    // after a stall handoff swaps the primary for the fallback.
    private val activeDownloaders = mutableMapOf<String, FileDownloader>()

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
        val handle = handles.remove(spec.id)
        val owner = activeDownloaders.remove(spec.id) ?: downloader
        handle?.let(owner::cancel)
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
        // Start on the primary (system DownloadManager). `active` swaps to the fallback
        // in-app HTTP downloader if the primary stalls (Android 15 scheduler deferral).
        var active: FileDownloader = downloader
        var usedFallback = false
        var handle = runCatching { active.enqueue(spec.url, spec.label, allowMetered) }
            .getOrElse {
                Log.w(TAG, "enqueue failed for ${spec.id}", it)
                setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                return
            }
        handles[spec.id] = handle
        activeDownloaders[spec.id] = active

        // Watchdog runs only against the primary; once we are on the fallback we commit to it.
        val stall = StallDetector(stallThresholdMs, now)

        while (true) {
            val status = runCatching { active.status(handle) }.getOrElse {
                setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                return
            }
            when (status.state) {
                RawDownloadState.PENDING, RawDownloadState.RUNNING -> {
                    val total = if (status.totalBytes > 0L) status.totalBytes else spec.sizeBytes
                    setState(spec.id, ModelDownloadState.Downloading(status.bytesSoFar, total))
                    if (!usedFallback && stall.isStalled(status.bytesSoFar)) {
                        // The primary is not moving. Fall back to the direct path — unless
                        // the user declined metered data AND we are on a metered network,
                        // in which case the stall is legitimate policy waiting (DownloadManager
                        // is correctly holding for Wi-Fi): keep waiting on the primary.
                        if (allowMetered || !isMetered()) {
                            Log.w(TAG, "primary download stalled for ${spec.id}; falling back to direct HTTP")
                            runCatching { active.cancel(handle) }
                            active = fallbackDownloader
                            usedFallback = true
                            handle = runCatching { active.enqueue(spec.url, spec.label, allowMetered) }
                                .getOrElse {
                                    Log.w(TAG, "fallback enqueue failed for ${spec.id}", it)
                                    handles.remove(spec.id)
                                    activeDownloaders.remove(spec.id)
                                    setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                                    return
                                }
                            handles[spec.id] = handle
                            activeDownloaders[spec.id] = active
                        }
                    }
                    delay(pollIntervalMs)
                }
                RawDownloadState.FAILED -> {
                    active.cancel(handle)
                    handles.remove(spec.id)
                    activeDownloaders.remove(spec.id)
                    setState(spec.id, ModelDownloadState.Failed(FailReason.NETWORK))
                    return
                }
                RawDownloadState.SUCCESS -> break
            }
        }

        setState(spec.id, ModelDownloadState.Verifying)
        val staged = active.stagedFile(handle)
        if (staged == null) {
            active.cancel(handle)
            handles.remove(spec.id)
            activeDownloaders.remove(spec.id)
            setState(spec.id, ModelDownloadState.Failed(FailReason.STORAGE))
            return
        }

        val result = store.install(staged, spec)
        active.cancel(handle) // clear the downloader record + its staging copy
        handles.remove(spec.id)
        activeDownloaders.remove(spec.id)

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
        // How long the primary download may make zero forward progress before we give up
        // on the system scheduler and pump the bytes ourselves. The single source of truth
        // for the stall threshold (Android 15 RUNNABLE-never-active symptom, #13).
        const val DEFAULT_STALL_MS = 15_000L
    }
}
