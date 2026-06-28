package pl.nech.tuparles

import android.content.Context
import android.content.SharedPreferences

/**
 * SharedPreferences-backed settings — the phone half of the "it's a setting"
 * doctrine: a smart default plus a total override for every behaviour. One store,
 * read by the IME, the scratchpad, the harness, and the bootstrap.
 */
object Settings {
    private const val PREFS = "tuparles"

    const val KEY_LANG = "lang" // auto | fr | en
    const val KEY_POSTPROCESS = "postprocess" // Boolean
    const val KEY_MODEL = "model" // chosen .bin filename, or "" = bundled/first pushed
    const val KEY_ANALYTICS = "analytics" // Boolean — domovoy telemetry on/off
    const val KEY_VERBOSE = "verbose" // Boolean — verbose debug file logging

    fun prefs(c: Context): SharedPreferences =
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun lang(c: Context): String = prefs(c).getString(KEY_LANG, "auto") ?: "auto"
    fun postprocessOn(c: Context): Boolean = prefs(c).getBoolean(KEY_POSTPROCESS, true)
    fun model(c: Context): String = prefs(c).getString(KEY_MODEL, "") ?: ""
    fun analyticsOn(c: Context): Boolean = prefs(c).getBoolean(KEY_ANALYTICS, true)
    fun verbose(c: Context): Boolean = prefs(c).getBoolean(KEY_VERBOSE, false)

    fun set(c: Context, key: String, value: Boolean) {
        prefs(c).edit().putBoolean(key, value).apply()
    }

    fun set(c: Context, key: String, value: String) {
        prefs(c).edit().putString(key, value).apply()
    }
}
