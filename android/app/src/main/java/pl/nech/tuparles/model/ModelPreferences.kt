package pl.nech.tuparles.model

import android.content.Context
import androidx.core.content.edit
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The one persisted model preference: which model the user actively selected. Null means
 * "no explicit choice" — resolution then falls back to the recommended default / any
 * installed model (see [ModelResolution]). An interface so the model manager's logic can
 * be unit-tested with an in-memory stand-in.
 */
interface ModelPreferences {
    var activeModelId: String?

    /** Whether the user dismissed the first-run "download a model" card (don't nag). */
    var firstRunCardDismissed: Boolean
}

@Singleton
class SharedPrefsModelPreferences @Inject constructor(
    @ApplicationContext context: Context,
) : ModelPreferences {
    private val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    override var activeModelId: String?
        get() = prefs.getString(KEY_ACTIVE, null)
        set(value) = prefs.edit {
            if (value == null) remove(KEY_ACTIVE) else putString(KEY_ACTIVE, value)
        }

    override var firstRunCardDismissed: Boolean
        get() = prefs.getBoolean(KEY_CARD_DISMISSED, false)
        set(value) = prefs.edit { putBoolean(KEY_CARD_DISMISSED, value) }

    private companion object {
        const val NAME = "tuparles_models"
        const val KEY_ACTIVE = "active_model_id"
        const val KEY_CARD_DISMISSED = "first_run_card_dismissed"
    }
}
