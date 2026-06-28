package pl.nech.tuparles

import android.content.res.AssetManager
import com.whispercpp.whisper.WhisperContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Process-scoped home for the heavyweight whisper model. Loading a GGML model
 * takes seconds, so it must NOT be tied to the Activity lifecycle — an Activity
 * recreation (rotation, uiMode change, "don't keep activities") re-attaches to
 * the already-loaded context here instead of reloading. The mutex makes a
 * concurrent double-load impossible.
 */
object Engine {
    @Volatile
    var whisper: WhisperContext? = null
        private set

    @Volatile
    var loadedFrom: String = ""
        private set

    val ready: Boolean get() = whisper != null

    private val loadMutex = Mutex()

    /** A model pushed to external files (power users / dev push the large model). */
    suspend fun ensureModelFromFile(modelPath: String) {
        if (whisper != null) return
        loadMutex.withLock {
            if (whisper != null) return
            whisper = withContext(Dispatchers.Default) {
                WhisperContext.createContextFromFile(modelPath)
            }
            loadedFrom = modelPath.substringAfterLast('/')
        }
    }

    /** The model bundled in the APK assets — the self-contained default. */
    suspend fun ensureModelFromAsset(assets: AssetManager, assetPath: String) {
        if (whisper != null) return
        loadMutex.withLock {
            if (whisper != null) return
            whisper = withContext(Dispatchers.Default) {
                WhisperContext.createContextFromAsset(assets, assetPath)
            }
            loadedFrom = "asset:${assetPath.substringAfterLast('/')}"
        }
    }

    /** Release the current model so the next ensure* loads a different one — the
     *  switch behind the model selector. Frees the native context's memory first. */
    suspend fun reset() {
        loadMutex.withLock {
            whisper?.release()
            whisper = null
            loadedFrom = ""
        }
    }
}
