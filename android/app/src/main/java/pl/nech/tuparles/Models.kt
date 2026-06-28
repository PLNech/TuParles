package pl.nech.tuparles

import android.content.Context
import java.io.File

/**
 * Model discovery + loading, shared by the IME, the scratchpad, and the harness.
 * On the phone there's a single inference backend (whisper.cpp), so "engine" means
 * the GGML model/quant rung: the bundled fast `base`, or a larger model pushed to
 * external files for quality. Selection persists in Settings and hot-swaps the
 * Engine context — the phone's expression of the desktop's engine gradient.
 */
object Models {
    const val BUNDLED = "ggml-base.bin"
    private const val TAG = "TuParles"

    /** One selectable model rung. `pushed` = a .bin in external files; else bundled. */
    data class ModelInfo(val key: String, val label: String, val pushed: Boolean, val sizeMb: Long)

    private fun pushedDir(c: Context) = c.getExternalFilesDir("models")

    /** The bundled fast default first, then any larger models pushed for quality. */
    fun available(c: Context): List<ModelInfo> {
        val pushed = pushedDir(c)?.listFiles { f -> f.isFile && f.name.endsWith(".bin") }
            ?.sortedBy { it.name }
            ?.map {
                ModelInfo(
                    it.name,
                    it.name.removePrefix("ggml-").removeSuffix(".bin"),
                    pushed = true,
                    sizeMb = it.length() / 1_000_000,
                )
            } ?: emptyList()
        return listOf(ModelInfo(BUNDLED, "base · intégré", pushed = false, sizeMb = 0L)) + pushed
    }

    /** The configured model, falling back to the bundled default. */
    fun chosenKey(c: Context): String =
        Settings.model(c).ifEmpty { BUNDLED }

    /** (Re)load a specific model, releasing the current one — the engine switch. */
    suspend fun load(c: Context, info: ModelInfo) {
        Engine.reset()
        if (info.pushed) {
            pushedDir(c)?.let { Engine.ensureModelFromFile(File(it, info.key).absolutePath) }
        } else {
            Engine.ensureModelFromAsset(c.assets, "models/$BUNDLED")
        }
        // Persist as "" for the bundled default so a fresh box still resolves it.
        Settings.set(c, Settings.KEY_MODEL, if (info.pushed) info.key else "")
        DebugLog.i(TAG, "model: switched to ${info.label} -> ${Engine.loadedFrom}")
    }

    /** Load the configured model into Engine if nothing is loaded yet. */
    suspend fun ensureLoaded(c: Context) {
        if (Engine.ready) return
        val want = Settings.model(c)
        val pushed = pushedDir(c)?.listFiles { f -> f.isFile && f.name.endsWith(".bin") }
        val file = pushed?.firstOrNull { it.name == want }
            ?: pushed?.firstOrNull { want.isEmpty() }
        if (file != null) {
            DebugLog.i(TAG, "model: loading pushed ${file.name} (${file.length() / 1_000_000} MB)")
            Engine.ensureModelFromFile(file.absolutePath)
        } else {
            DebugLog.i(TAG, "model: loading bundled $BUNDLED")
            Engine.ensureModelFromAsset(c.assets, "models/$BUNDLED")
        }
    }
}
