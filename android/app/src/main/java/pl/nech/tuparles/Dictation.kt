package pl.nech.tuparles

import com.chaquo.python.PyObject
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import pl.nech.domovoy.analytics.DomovoyAnalytics

/** One decode's result, shared by every surface (IME, scratchpad, harness). */
data class Take(
    val raw: String,
    val clean: String,
    val ms: Long,
    val seconds: Float,
    val lang: String,
    val model: String,
)

/**
 * The single decode path: PCM samples → whisper.cpp (native, on-device) →
 * tuparles.pipeline.postprocess() (embedded CPython). The SAME two stages the
 * desktop daemon runs, so the phone and the desktop can't diverge. The IME, the
 * scratchpad, and the capture harness ALL call this — never the engine directly —
 * so postprocess, timing, and telemetry stay identical across surfaces (the phone
 * mirror of the desktop's shared pipeline.postprocess() contract).
 */
object Dictation {
    private const val TAG = "TuParles"
    private const val DECODE_TIMEOUT_MS = 90_000L // a runaway decode fails visibly

    @Volatile private var postprocess: PyObject? = null

    private fun postprocessModule(): PyObject {
        postprocess?.let { return it }
        check(Python.isStarted()) { "Python not started (TuParlesApp.onCreate should have)" }
        return Python.getInstance().getModule("tuparles.pipeline").also { postprocess = it }
    }

    /**
     * Decode + clean. `postprocessOn=false` returns the raw decode (in both fields).
     * Throws on no model / timeout — callers render the error; they never see a hang.
     * Telemetry carries timing + shape only, NEVER the dictated text (privacy).
     */
    suspend fun decode(samples: ShortArray, lang: String, postprocessOn: Boolean, threads: Int = 0): Take {
        val ctx = Engine.whisper ?: error("model not loaded")
        val seconds = samples.size.toFloat() / SAMPLE_RATE
        if (samples.isEmpty()) return Take("", "", 0L, 0f, lang, Engine.loadedFrom)

        DomovoyAnalytics.startSpan("decode")
        val t0 = System.currentTimeMillis()
        val raw = withTimeout(DECODE_TIMEOUT_MS) {
            withContext(Dispatchers.Default) {
                ctx.transcribeData(samples.toFloats(), printTimestamp = false, language = lang, threads = threads).trim()
            }
        }
        val ms = System.currentTimeMillis() - t0
        val clean = if (postprocessOn) {
            withContext(Dispatchers.Default) {
                postprocessModule().callAttr("postprocess", raw)?.toString() ?: raw
            }
        } else {
            raw
        }
        val rtf = if (seconds > 0f) ms / 1000f / seconds else 0f
        DebugLog.i(
            TAG,
            "decode: ${ms}ms lang=$lang model=${Engine.loadedFrom} " +
                "audio=${"%.1f".format(seconds)}s rtf=${"%.2f".format(rtf)} chars=${clean.length}",
        )
        DomovoyAnalytics.finishSpan(
            "decode",
            mapOf(
                "lang" to lang,
                "model" to Engine.loadedFrom,
                "audio_ms" to (seconds * 1000f).toLong().toString(),
                "chars" to clean.length.toString(),
                "rtf" to "%.2f".format(rtf),
                "postprocess" to postprocessOn.toString(),
            ),
        )
        return Take(raw, clean, ms, seconds, lang, Engine.loadedFrom)
    }
}
