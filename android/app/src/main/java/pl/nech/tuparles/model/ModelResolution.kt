package pl.nech.tuparles.model

/**
 * The engine's model-resolution *order*, as a pure function so it can be unit-tested
 * without a device, an AssetManager, or the filesystem. The order (issue #13):
 *
 *   1. the user's actively-selected model, if it is downloaded  (total override)
 *   2. else the recommended default, if it is downloaded         (smart default)
 *   3. else any other downloaded model, in catalog order         (something beats nothing)
 *   4. else the bundled asset, if this build shipped one         (dev fallback)
 *   5. else null                                                 (record-only mode)
 *
 * Downloaded models always win over the bundled asset: a fresh, user-chosen model on
 * disk should not be shadowed by a stale dev asset.
 */
object ModelResolution {

    sealed interface Choice {
        data class Downloaded(val spec: ModelSpec) : Choice
        data object Bundled : Choice
    }

    fun resolve(
        activeId: String?,
        installedIds: Set<String>,
        bundledAssetPresent: Boolean,
    ): Choice? {
        ModelCatalog.byId(activeId)?.let { active ->
            if (active.id in installedIds) return Choice.Downloaded(active)
        }
        val recommended = ModelCatalog.recommended
        if (recommended.id in installedIds) return Choice.Downloaded(recommended)

        ModelCatalog.models.firstOrNull { it.id in installedIds }?.let {
            return Choice.Downloaded(it)
        }
        if (bundledAssetPresent) return Choice.Bundled
        return null
    }
}
