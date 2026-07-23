package pl.nech.tuparles.model

import dagger.Lazy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * The download coordinator's state machine + safety invariant, driven with a fake
 * downloader and a temp-dir store — no Android, no network. Uses a custom small [ModelSpec]
 * so the sha256-before-activation gate can be exercised with real bytes.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ModelManagerTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun manager(
        downloader: FileDownloader,
        store: ModelStore,
        scope: CoroutineScope,
        prefs: ModelPreferences = FakeModelPreferences(),
        bundled: Boolean = false,
        pending: PendingWork = RecordingPendingWork(),
    ) = ModelManager(
        store = store,
        downloader = downloader,
        prefs = prefs,
        scope = scope,
        bundledAssetPresent = bundled,
        pending = Lazy { pending },
        pollIntervalMs = 1L,
    )

    private fun specFor(bytes: ByteArray) = ModelSpec(
        id = "dl-test",
        fileName = "ggml-dltest.bin",
        label = "Test",
        character = "test",
        sizeBytes = bytes.size.toLong(),
        sha256 = sha256Of(bytes),
    )

    @Test
    fun happy_path_reaches_ready_installs_and_wakes_pending_notes() = runTest {
        val bytes = "verified model bytes".toByteArray()
        val spec = specFor(bytes)
        val staged = tmp.newFile("staged.bin").apply { writeBytes(bytes) }
        val downloader = FakeFileDownloader(
            script = listOf(
                DownloadStatus(RawDownloadState.RUNNING, 5L, 20L),
                DownloadStatus(RawDownloadState.SUCCESS, 20L, 20L),
            ),
            staged = { staged },
        )
        val store = ModelStore(tmp.newFolder("models"))
        val pending = RecordingPendingWork()
        val mgr = manager(downloader, store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)), pending = pending)

        mgr.startDownload(spec, allowMetered = true)
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Ready, mgr.downloads.value[spec.id])
        assertTrue("model file installed", store.fileFor(spec).exists())
        assertEquals("pending notes woken exactly once", 1, pending.retries)
        assertTrue("staging cleaned", downloader.cancelled >= 1)
    }

    @Test
    fun a_corrupt_download_fails_checksum_and_never_wakes_pending() = runTest {
        val spec = specFor("the real bytes".toByteArray())
        // Same length, wrong content → passes size, fails sha256.
        val staged = tmp.newFile("staged.bin").apply { writeBytes(ByteArray(spec.sizeBytes.toInt()) { 1 }) }
        val downloader = FakeFileDownloader(
            script = listOf(DownloadStatus(RawDownloadState.SUCCESS, spec.sizeBytes, spec.sizeBytes)),
            staged = { staged },
        )
        val store = ModelStore(tmp.newFolder("models"))
        val pending = RecordingPendingWork()
        val mgr = manager(downloader, store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)), pending = pending)

        mgr.startDownload(spec, allowMetered = true)
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Failed(FailReason.CHECKSUM), mgr.downloads.value[spec.id])
        assertFalse("corrupt model never activated", store.fileFor(spec).exists())
        assertEquals("pending NOT woken by a failed download", 0, pending.retries)
    }

    @Test
    fun a_network_failure_reports_failed_network() = runTest {
        val spec = specFor("bytes".toByteArray())
        val downloader = FakeFileDownloader(
            script = listOf(DownloadStatus(RawDownloadState.FAILED, 0L, 0L)),
            staged = { null },
        )
        val store = ModelStore(tmp.newFolder("models"))
        val mgr = manager(downloader, store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))

        mgr.startDownload(spec, allowMetered = true)
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Failed(FailReason.NETWORK), mgr.downloads.value[spec.id])
    }

    @Test
    fun downloading_an_already_installed_model_is_immediately_ready() = runTest {
        val bytes = "already here".toByteArray()
        val spec = specFor(bytes)
        val dir = tmp.newFolder("models")
        File(dir, spec.fileName).writeBytes(bytes) // pre-installed, exact size
        val store = ModelStore(dir)
        val downloader = FakeFileDownloader(script = listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), staged = { null })
        val mgr = manager(downloader, store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))

        mgr.startDownload(spec, allowMetered = true)
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Ready, mgr.downloads.value[spec.id])
        assertEquals("no network touched for an installed model", 0, downloader.enqueued)
    }

    @Test
    fun a_stalled_primary_download_falls_back_to_the_direct_path_and_completes() = runTest {
        val bytes = "the fallback delivered these bytes".toByteArray()
        val spec = specFor(bytes)
        val staged = tmp.newFile("fb.bin").apply { writeBytes(bytes) }
        // Primary never progresses: PENDING, 0 bytes, forever (the Android-15 symptom).
        val primary = FakeFileDownloader(
            script = listOf(DownloadStatus(RawDownloadState.PENDING, 0L, spec.sizeBytes)),
            staged = { null },
        )
        // Fallback delivers immediately.
        val fallback = FakeFileDownloader(
            script = listOf(DownloadStatus(RawDownloadState.SUCCESS, spec.sizeBytes, spec.sizeBytes)),
            staged = { staged },
        )
        val store = ModelStore(tmp.newFolder("models"))
        val pending = RecordingPendingWork()
        var clock = 0L
        val mgr = ModelManager(
            store = store, downloader = primary, prefs = FakeModelPreferences(),
            scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler)),
            bundledAssetPresent = false, pending = Lazy { pending }, pollIntervalMs = 1L,
            fallbackDownloader = fallback, isMetered = { false },
            now = { clock += 10_000L; clock }, stallThresholdMs = 15_000L,
        )

        mgr.startDownload(spec, allowMetered = true)
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Ready, mgr.downloads.value[spec.id])
        assertTrue("model installed via the fallback", store.fileFor(spec).exists())
        assertEquals("pending notes woken once", 1, pending.retries)
        assertEquals("fallback was enqueued exactly once", 1, fallback.enqueued)
        assertTrue("stalled primary was cancelled", primary.cancelled >= 1)
    }

    @Test
    fun a_stall_on_metered_data_the_user_declined_does_not_force_the_fallback() = runTest {
        val bytes = "primary eventually delivers".toByteArray()
        val spec = specFor(bytes)
        val staged = tmp.newFile("pri.bin").apply { writeBytes(bytes) }
        // Primary stalls past the threshold, then finally succeeds (DownloadManager holding
        // for Wi-Fi, then catching up) — the fallback must never be reached.
        val primary = FakeFileDownloader(
            script = listOf(
                DownloadStatus(RawDownloadState.PENDING, 0L, spec.sizeBytes),
                DownloadStatus(RawDownloadState.PENDING, 0L, spec.sizeBytes),
                DownloadStatus(RawDownloadState.PENDING, 0L, spec.sizeBytes),
                DownloadStatus(RawDownloadState.PENDING, 0L, spec.sizeBytes),
                DownloadStatus(RawDownloadState.SUCCESS, spec.sizeBytes, spec.sizeBytes),
            ),
            staged = { staged },
        )
        val fallback = FakeFileDownloader(
            script = listOf(DownloadStatus(RawDownloadState.SUCCESS, spec.sizeBytes, spec.sizeBytes)),
            staged = { staged },
        )
        val store = ModelStore(tmp.newFolder("models"))
        var clock = 0L
        val mgr = ModelManager(
            store = store, downloader = primary, prefs = FakeModelPreferences(),
            scope = CoroutineScope(UnconfinedTestDispatcher(testScheduler)),
            bundledAssetPresent = false, pending = Lazy { RecordingPendingWork() }, pollIntervalMs = 1L,
            fallbackDownloader = fallback,
            isMetered = { true }, // active network is metered
            now = { clock += 10_000L; clock }, stallThresholdMs = 15_000L,
        )

        mgr.startDownload(spec, allowMetered = false) // user declined cellular
        advanceUntilIdle()

        assertEquals(ModelDownloadState.Ready, mgr.downloads.value[spec.id])
        assertEquals("fallback NOT used on declined metered data", 0, fallback.enqueued)
    }

    @Test
    fun resolver_prefers_a_downloaded_catalog_model_then_bundled_then_none() = runTest {
        val dir = tmp.newFolder("models")
        val store = ModelStore(dir)

        // Nothing installed, no asset → record-only.
        val none = manager(
            FakeFileDownloader(listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), { null }),
            store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)),
        )
        assertFalse(none.hasModel())
        assertEquals(null, none.current())

        // Nothing installed but a bundled asset present → BundledAsset.
        val bundled = manager(
            FakeFileDownloader(listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), { null }),
            store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)), bundled = true,
        )
        assertTrue(bundled.current() is ModelSource.BundledAsset)

        // A downloaded catalog model (sparse, exact size) wins over the asset.
        sparseFile(File(dir, "ggml-small.bin"), ModelCatalog.byId("small-f16")!!.sizeBytes)
        val downloaded = manager(
            FakeFileDownloader(listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), { null }),
            store, CoroutineScope(UnconfinedTestDispatcher(testScheduler)), bundled = true,
        )
        val src = downloaded.current()
        assertTrue(src is ModelSource.DownloadedFile)
        assertTrue((src as ModelSource.DownloadedFile).path.endsWith("ggml-small.bin"))
    }
}
