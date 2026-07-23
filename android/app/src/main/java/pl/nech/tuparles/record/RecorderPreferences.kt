package pl.nech.tuparles.record

import android.content.Context
import androidx.core.content.edit
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persisted recorder settings. House rule "it's a setting — smart default, total override":
 * the rolling committed transcript is ON by default (it is the record-minutes-and-pray fix),
 * with a Réglages toggle for anyone who prefers the old single post-hoc decode. An interface
 * so the recording logic can be unit-tested with an in-memory stand-in.
 */
interface RecorderPreferences {
    /** Whether to decode + persist segments during recording (default true). */
    var rollingTranscriptEnabled: Boolean
}

@Singleton
class SharedPrefsRecorderPreferences @Inject constructor(
    @ApplicationContext context: Context,
) : RecorderPreferences {
    private val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    override var rollingTranscriptEnabled: Boolean
        get() = prefs.getBoolean(KEY_ROLLING, true)
        set(value) = prefs.edit { putBoolean(KEY_ROLLING, value) }

    private companion object {
        const val NAME = "tuparles_recorder"
        const val KEY_ROLLING = "rolling_transcript_enabled"
    }
}
