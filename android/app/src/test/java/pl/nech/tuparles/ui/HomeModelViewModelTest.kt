package pl.nech.tuparles.ui

import dagger.Lazy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import pl.nech.tuparles.model.FakeFileDownloader
import pl.nech.tuparles.model.FakeModelPreferences
import pl.nech.tuparles.model.ModelCatalog
import pl.nech.tuparles.model.ModelManager
import pl.nech.tuparles.model.ModelPreferences
import pl.nech.tuparles.model.ModelStore
import pl.nech.tuparles.model.PendingWork
import pl.nech.tuparles.model.RawDownloadState
import pl.nech.tuparles.model.DownloadStatus
import pl.nech.tuparles.model.RecordingPendingWork
import pl.nech.tuparles.model.sparseFile
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class HomeModelViewModelTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun manager(dir: File, prefs: ModelPreferences, scope: CoroutineScope, pending: PendingWork = RecordingPendingWork()) =
        ModelManager(
            store = ModelStore(dir),
            downloader = FakeFileDownloader(listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), { null }),
            prefs = prefs,
            scope = scope,
            bundledAssetPresent = false,
            pending = Lazy { pending },
        )

    @Test
    fun fresh_install_with_no_model_shows_the_first_run_card() = runTest(dispatcher) {
        val prefs = FakeModelPreferences()
        val mgr = manager(tmp.newFolder("m"), prefs, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))
        val vm = HomeModelViewModel(mgr, prefs)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.state.collect {} }
        advanceUntilIdle()

        assertFalse(vm.state.value.modelReady)
        assertTrue(vm.state.value.showFirstRunCard)
    }

    @Test
    fun dismissing_the_card_hides_it_and_persists() = runTest(dispatcher) {
        val prefs = FakeModelPreferences()
        val mgr = manager(tmp.newFolder("m"), prefs, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))
        val vm = HomeModelViewModel(mgr, prefs)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.state.collect {} }
        advanceUntilIdle()

        vm.dismissCard()
        advanceUntilIdle()

        assertFalse(vm.state.value.showFirstRunCard)
        assertTrue("dismissal persisted", prefs.firstRunCardDismissed)
    }

    @Test
    fun with_a_model_installed_the_card_is_gone_and_transcription_is_ready() = runTest(dispatcher) {
        val dir = tmp.newFolder("m")
        sparseFile(File(dir, "ggml-small.bin"), ModelCatalog.byId("small-f16")!!.sizeBytes)
        val prefs = FakeModelPreferences()
        val mgr = manager(dir, prefs, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))
        val vm = HomeModelViewModel(mgr, prefs)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.state.collect {} }
        advanceUntilIdle()

        assertTrue(vm.state.value.modelReady)
        assertFalse(vm.state.value.showFirstRunCard)
    }
}
