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
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import pl.nech.tuparles.model.DownloadStatus
import pl.nech.tuparles.model.FakeFileDownloader
import pl.nech.tuparles.model.FakeModelPreferences
import pl.nech.tuparles.model.ModelCatalog
import pl.nech.tuparles.model.ModelManager
import pl.nech.tuparles.model.ModelStore
import pl.nech.tuparles.model.RawDownloadState
import pl.nech.tuparles.model.RecordingPendingWork
import pl.nech.tuparles.model.sparseFile
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class ModelsViewModelTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun manager(dir: File, prefs: FakeModelPreferences, scope: CoroutineScope) =
        ModelManager(
            store = ModelStore(dir),
            downloader = FakeFileDownloader(listOf(DownloadStatus(RawDownloadState.FAILED, 0, 0)), { null }),
            prefs = prefs,
            scope = scope,
            bundledAssetPresent = false,
            pending = Lazy { RecordingPendingWork() },
        )

    @Test
    fun rows_cover_the_whole_catalog_with_install_and_active_state() = runTest(dispatcher) {
        val dir = tmp.newFolder("m")
        val small = ModelCatalog.byId("small-f16")!!
        sparseFile(File(dir, small.fileName), small.sizeBytes)
        val prefs = FakeModelPreferences()
        val mgr = manager(dir, prefs, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))
        val vm = ModelsViewModel(mgr)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(ModelCatalog.models.size, state.rows.size)
        val smallRow = state.rows.first { it.spec.id == "small-f16" }
        assertTrue(smallRow.installed)
        // No explicit choice yet, but the recommended (small) is installed → effectively active.
        assertTrue(smallRow.active)
        assertEquals(small.sizeBytes, state.totalBytesUsed)
        assertTrue(state.anyInstalled)
        assertFalse(state.rows.first { it.spec.id == "tiny-q5_1" }.installed)
    }

    @Test
    fun selecting_an_installed_model_makes_it_the_active_one() = runTest(dispatcher) {
        val dir = tmp.newFolder("m")
        val tiny = ModelCatalog.byId("tiny-q5_1")!!
        val small = ModelCatalog.byId("small-f16")!!
        sparseFile(File(dir, tiny.fileName), tiny.sizeBytes)
        sparseFile(File(dir, small.fileName), small.sizeBytes)
        val prefs = FakeModelPreferences()
        val mgr = manager(dir, prefs, CoroutineScope(UnconfinedTestDispatcher(testScheduler)))
        val vm = ModelsViewModel(mgr)
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.uiState.collect {} }
        advanceUntilIdle()

        // Default: recommended (small) is the effective active.
        assertTrue(vm.uiState.value.rows.first { it.spec.id == "small-f16" }.active)

        vm.select(tiny)
        advanceUntilIdle()

        val rows = vm.uiState.value.rows
        assertTrue("total override honoured", rows.first { it.spec.id == "tiny-q5_1" }.active)
        assertFalse(rows.first { it.spec.id == "small-f16" }.active)
        assertEquals("tiny-q5_1", prefs.activeModelId)
    }
}
