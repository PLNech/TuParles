package pl.nech.tuparles.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import pl.nech.tuparles.model.ModelCatalog
import pl.nech.tuparles.model.ModelDownloadState
import pl.nech.tuparles.model.ModelManager
import pl.nech.tuparles.model.ModelPreferences
import pl.nech.tuparles.model.ModelSpec
import javax.inject.Inject

/**
 * The home screen's slice of the model world: is a model ready (so transcription runs),
 * and should the first-run "download a model" card show. Kept separate from
 * [RecorderViewModel] so the recorder/search logic — and its tests — stay untouched by
 * the lean-APK change.
 */
data class HomeModelState(
    val modelReady: Boolean = false,
    val showFirstRunCard: Boolean = false,
    val recommendedDownload: ModelDownloadState = ModelDownloadState.Idle,
) {
    val recommended: ModelSpec get() = ModelCatalog.recommended
}

@HiltViewModel
class HomeModelViewModel @Inject constructor(
    private val manager: ModelManager,
    private val prefs: ModelPreferences,
) : ViewModel() {

    private val cardDismissed = MutableStateFlow(prefs.firstRunCardDismissed)

    val state: StateFlow<HomeModelState> =
        combine(manager.installedIds, manager.downloads, cardDismissed) { installed, downloads, dismissed ->
            val ready = installed.isNotEmpty() || manager.hasBundledAsset
            HomeModelState(
                modelReady = ready,
                // Offer the download once, until there is a model or the user dismisses it.
                showFirstRunCard = !ready && !dismissed,
                recommendedDownload = downloads[ModelCatalog.recommended.id] ?: ModelDownloadState.Idle,
            )
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), HomeModelState())

    fun downloadRecommended(allowMetered: Boolean) =
        manager.startDownload(ModelCatalog.recommended, allowMetered)

    fun dismissCard() {
        prefs.firstRunCardDismissed = true
        cardDismissed.value = true
    }
}
