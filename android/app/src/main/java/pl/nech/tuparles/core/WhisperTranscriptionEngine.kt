package pl.nech.tuparles.core

import android.content.Context
import android.util.Log
import com.whispercpp.whisper.WhisperContext
import dagger.hilt.android.qualifiers.ApplicationContext
import pl.nech.tuparles.record.decodeWavToFloats
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * On-device speech-to-text via the vendored `:whisper` module (whisper.cpp + JNI).
 *
 * Three POC lessons are baked in:
 *  - **process-scoped singleton**: the ~142MB model context is loaded once (Hilt
 *    @Singleton + lazy, mutex-guarded init) and reused across notes — never per-decode.
 *  - **language = "auto"**: NEVER hardcode a language. The POC's historic FR→EN bug
 *    came from a hardcoded "en"; code-switch dictation needs auto-detect.
 *  - **model as an uncompressed asset**: shipped at assets/[MODEL_ASSET], loaded via
 *    the AAssetManager loader (no full inflate). Fetched by scripts/fetch-android-model.sh.
 *
 * Graceful degradation (house doctrine): if the model asset is absent, [available] is
 * false and [transcribe] is never called — the app falls back to Phase A (audio-only),
 * because the desktop can always re-transcribe the WAV at higher quality later.
 */
@Singleton
class WhisperTranscriptionEngine @Inject constructor(
    @ApplicationContext private val context: Context,
) : TranscriptionEngine {

    // All native decode access is serialized through the gate so the non-thread-safe
    // whisper singleton is touched by one decode at a time; committed decodes win, live
    // partials skip when busy (#42). Context creation happens under the gate too.
    private val gate = DecodeGate()
    @Volatile private var whisper: WhisperContext? = null

    /** True iff the model asset is bundled in this build. Evaluated once. */
    override val available: Boolean by lazy { assetExists(MODEL_ASSET) }

    /** Partials ride the same native engine; if it can decode a note, it can decode a window. */
    override val supportsPartials: Boolean get() = available

    override suspend fun transcribe(wavPath: String): Transcript {
        check(available) { "No on-device model bundled ($MODEL_ASSET); engine unavailable." }
        val samples = decodeWavToFloats(File(wavPath))
        // Committed decode: waits its turn on the gate, then runs to completion.
        return gate.committed {
            val ctx = ensureContext()
            // language="auto" (default) — let whisper detect FR/EN per the code-switch story.
            val raw = ctx.transcribeData(samples, printTimestamp = false)
            Transcript(text = raw.trim(), language = null, model = MODEL_NAME)
        }
    }

    override suspend fun transcribeSamples(samples: FloatArray): String? {
        if (!available || samples.isEmpty()) return null
        // Partial decode: skips (null) when a committed decode holds the engine.
        return gate.partial {
            val ctx = ensureContext()
            ctx.transcribeData(samples, printTimestamp = false).trim()
        }
    }

    /** Lazily load the ~142MB model once. Always called under [gate], so no extra lock. */
    private suspend fun ensureContext(): WhisperContext =
        whisper ?: run {
            Log.i(TAG, "Loading whisper model from asset '$MODEL_ASSET' (once)")
            WhisperContext.createContextFromAsset(context.assets, MODEL_ASSET).also { whisper = it }
        }

    private fun assetExists(path: String): Boolean = runCatching {
        context.assets.open(path).close()
        true
    }.getOrDefault(false)

    private companion object {
        const val TAG = "TuParles"
        // Default Phase B bundle: ggml base (142MB). The quality/speed sweet-spot
        // exploration (small / large-v3-turbo) is issue #13, not here.
        const val MODEL_ASSET = "models/ggml-base.bin"
        const val MODEL_NAME = "ggml-base"
    }
}
