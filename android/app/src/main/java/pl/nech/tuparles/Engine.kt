package pl.nech.tuparles

import com.whispercpp.whisper.WhisperContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Process-scoped home for the heavyweight whisper model. Loading the 547 MB
 * GGML model takes seconds, so it must NOT be tied to the Activity lifecycle —
 * an Activity recreation (rotation, uiMode change, "don't keep activities")
 * re-attaches to the already-loaded context here instead of reloading. The
 * mutex makes a concurrent double-load impossible.
 */
object Engine {
    @Volatile
    var whisper: WhisperContext? = null
        private set

    val ready: Boolean get() = whisper != null

    private val loadMutex = Mutex()

    suspend fun ensureModel(modelPath: String) {
        if (whisper != null) return
        loadMutex.withLock {
            if (whisper != null) return
            whisper = withContext(Dispatchers.Default) {
                WhisperContext.createContextFromFile(modelPath)
            }
        }
    }
}
