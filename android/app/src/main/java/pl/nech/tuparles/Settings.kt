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
    const val KEY_PRIVATE = "private_mode" // Boolean — master privacy switch
    const val KEY_SAVE_AUDIO = "save_audio" // Boolean — retain every take's WAV
    const val KEY_THREADS = "threads" // Int — whisper threads (0 = auto)
    const val KEY_PROMPT = "prompt" // String — initial_prompt vocab bias ("" = none)

    fun prefs(c: Context): SharedPreferences =
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun lang(c: Context): String = prefs(c).getString(KEY_LANG, "auto") ?: "auto"
    fun postprocessOn(c: Context): Boolean = prefs(c).getBoolean(KEY_POSTPROCESS, true)
    fun model(c: Context): String = prefs(c).getString(KEY_MODEL, "") ?: ""
    fun analyticsOn(c: Context): Boolean = prefs(c).getBoolean(KEY_ANALYTICS, true)
    fun verbose(c: Context): Boolean = prefs(c).getBoolean(KEY_VERBOSE, false)

    /**
     * Private mode: the master privacy switch. When ON, nothing touches disk or
     * leaves the process — debug file logging, domovoy analytics/sync, and raw take
     * audio are ALL suppressed (see DebugLog / DomovoySync / DictationService). The
     * "until back" escape hatch for sensitive periods; flip it off to resume.
     */
    fun privateMode(c: Context): Boolean = prefs(c).getBoolean(KEY_PRIVATE, false)
    fun saveAudio(c: Context): Boolean = prefs(c).getBoolean(KEY_SAVE_AUDIO, false)
    fun threads(c: Context): Int = prefs(c).getInt(KEY_THREADS, 0)

    /**
     * Vocab-biasing initial_prompt for whisper (e.g. "pipeline, refactor, commit,
     * deploy"). Empty = no bias (default, behaviour unchanged). Conservative by
     * doctrine: it nudges spelling/casing of known terms, it does not rewrite meaning.
     */
    fun prompt(c: Context): String = prefs(c).getString(KEY_PROMPT, "") ?: ""

    fun set(c: Context, key: String, value: Boolean) {
        prefs(c).edit().putBoolean(key, value).apply()
    }

    fun set(c: Context, key: String, value: String) {
        prefs(c).edit().putString(key, value).apply()
    }

    fun set(c: Context, key: String, value: Int) {
        prefs(c).edit().putInt(key, value).apply()
    }
}
