package pl.nech.tuparles.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The engine's model-resolution *order* (pure): active → recommended → any → bundled → none. */
class ModelResolutionTest {

    private val recommended = ModelCatalog.recommended.id
    private val tiny = "tiny-q5_1"
    private val medium = "medium-q5_0"

    @Test
    fun nothing_installed_and_no_asset_resolves_to_null() {
        assertNull(ModelResolution.resolve(activeId = null, installedIds = emptySet(), bundledAssetPresent = false))
    }

    @Test
    fun bundled_asset_is_the_last_resort_when_nothing_is_downloaded() {
        val choice = ModelResolution.resolve(null, emptySet(), bundledAssetPresent = true)
        assertEquals(ModelResolution.Choice.Bundled, choice)
    }

    @Test
    fun a_downloaded_model_always_wins_over_the_bundled_asset() {
        val choice = ModelResolution.resolve(null, setOf(tiny), bundledAssetPresent = true)
        assertTrue(choice is ModelResolution.Choice.Downloaded)
        assertEquals(tiny, (choice as ModelResolution.Choice.Downloaded).spec.id)
    }

    @Test
    fun active_selection_wins_when_it_is_installed() {
        val choice = ModelResolution.resolve(medium, setOf(tiny, medium, recommended), bundledAssetPresent = false)
        assertEquals(medium, (choice as ModelResolution.Choice.Downloaded).spec.id)
    }

    @Test
    fun falls_back_to_recommended_when_the_active_choice_is_not_installed() {
        // active points at a model the user deleted; recommended is present → use it.
        val choice = ModelResolution.resolve(medium, setOf(tiny, recommended), bundledAssetPresent = false)
        assertEquals(recommended, (choice as ModelResolution.Choice.Downloaded).spec.id)
    }

    @Test
    fun falls_back_to_any_installed_in_catalog_order_when_no_active_and_no_recommended() {
        // Neither active nor recommended installed; pick the first installed by catalog order.
        val choice = ModelResolution.resolve(null, setOf(medium, tiny), bundledAssetPresent = false)
        assertEquals(tiny, (choice as ModelResolution.Choice.Downloaded).spec.id) // tiny precedes medium
    }
}
