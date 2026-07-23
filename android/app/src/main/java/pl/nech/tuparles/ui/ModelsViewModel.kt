package pl.nech.tuparles.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import pl.nech.tuparles.model.ModelCatalog
import pl.nech.tuparles.model.ModelDownloadState
import pl.nech.tuparles.model.ModelManager
import pl.nech.tuparles.model.ModelSpec
import pl.nech.tuparles.record.RecorderPreferences
import javax.inject.Inject

/** One catalog row as the Réglages model manager renders it. */
data class ModelRow(
    val spec: ModelSpec,
    val installed: Boolean,
    val active: Boolean,
    val download: ModelDownloadState,
)

/**
 * The model-manager surface (Réglages): the whole catalog with per-model install/active
 * state and any download in flight, plus total storage used. "Smart default, total
 * override" — the recommended model is marked, everything is one tap away.
 *
 * [activeEffective] is the id the engine would actually load right now (the explicit
 * selection if installed, else the recommended-if-installed, else any installed), so the
 * "actif" badge tells the truth even before the user makes an explicit choice.
 */
data class ModelsUiState(
    val rows: List<ModelRow> = emptyList(),
    val totalBytesUsed: Long = 0L,
    val anyInstalled: Boolean = false,
)

@HiltViewModel
class ModelsViewModel @Inject constructor(
    private val manager: ModelManager,
    private val recorderPrefs: RecorderPreferences,
) : ViewModel() {

    // "It's a setting": the rolling committed transcript is on by default, toggleable here.
    private val _rollingEnabled = MutableStateFlow(recorderPrefs.rollingTranscriptEnabled)
    val rollingEnabled: StateFlow<Boolean> = _rollingEnabled.asStateFlow()

    fun setRollingEnabled(enabled: Boolean) {
        recorderPrefs.rollingTranscriptEnabled = enabled
        _rollingEnabled.value = enabled
    }

    val uiState: StateFlow<ModelsUiState> =
        combine(manager.installedIds, manager.downloads, manager.activeId) { installed, downloads, activeId ->
            val effectiveActive = effectiveActiveId(activeId, installed)
            val rows = ModelCatalog.models.map { spec ->
                ModelRow(
                    spec = spec,
                    installed = spec.id in installed,
                    active = spec.id == effectiveActive,
                    download = downloads[spec.id] ?: ModelDownloadState.Idle,
                )
            }
            ModelsUiState(
                rows = rows,
                totalBytesUsed = ModelCatalog.models.filter { it.id in installed }.sumOf { it.sizeBytes },
                anyInstalled = installed.isNotEmpty(),
            )
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ModelsUiState())

    fun download(spec: ModelSpec, allowMetered: Boolean) = manager.startDownload(spec, allowMetered)
    fun cancel(spec: ModelSpec) = manager.cancel(spec)
    fun delete(spec: ModelSpec) = manager.delete(spec)
    fun select(spec: ModelSpec) = manager.select(spec)

    private fun effectiveActiveId(activeId: String?, installed: Set<String>): String? {
        if (activeId != null && activeId in installed) return activeId
        ModelCatalog.recommended.takeIf { it.id in installed }?.let { return it.id }
        return ModelCatalog.models.firstOrNull { it.id in installed }?.id
    }
}
