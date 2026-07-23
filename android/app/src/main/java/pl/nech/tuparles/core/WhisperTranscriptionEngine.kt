package pl.nech.tuparles.core

import android.content.Context
import android.util.Log
import com.whispercpp.whisper.WhisperContext
import dagger.hilt.android.qualifiers.ApplicationContext
import pl.nech.tuparles.model.ModelResolver
import pl.nech.tuparles.model.ModelSource
import pl.nech.tuparles.record.decodeWavToFloats
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * On-device speech-to-text via the vendored `:whisper` module (whisper.cpp + JNI).
 *
 * POC lessons baked in:
 *  - **process-scoped singleton**: the model context is loaded once (Hilt @Singleton +
 *    lazy, gate-guarded) and reused across notes — never per-decode.
 *  - **language = "auto"**: NEVER hardcode a language. The POC's historic FR→EN bug came
 *    from a hardcoded "en"; code-switch dictation needs auto-detect.
 *
 * The model is no longer a mandatory bundled asset (#13, app-weight goal): a lean APK
 * ships no weights, the user downloads a model, and the engine resolves *where* to load
 * from via [ModelResolver] — a downloaded file in app-private storage first, a bundled
 * asset (dev builds) second, else nothing. [available] tracks that live, so the moment a
 * model lands the engine reports itself ready without a wiring change.
 *
 * **Runtime model switch**: the native context is a non-thread-safe singleton, so every
 * touch goes through [gate]. [ensureContext] compares the resolved source against what is
 * loaded and, when they differ, releases the old context and loads the new one — all on
 * the committed path. A live partial that arrives mid-swap simply skips (the gate is
 * busy) and recording is never affected: graceful degradation, house style.
 */
@Singleton
class WhisperTranscriptionEngine @Inject constructor(
    @ApplicationContext private val context: Context,
    private val resolver: ModelResolver,
) : TranscriptionEngine {

    private val gate = DecodeGate()
    @Volatile private var whisper: WhisperContext? = null
    @Volatile private var loaded: ModelSource? = null

    /** True iff a model is resolvable right now (downloaded or bundled). Re-checked live. */
    override val available: Boolean get() = resolver.hasModel()

    override val supportsPartials: Boolean get() = available

    override suspend fun transcribe(wavPath: String): Transcript {
        val samples = decodeWavToFloats(File(wavPath))
        return gate.committed {
            val ctx = ensureContext()
            val raw = ctx.transcribeData(samples, printTimestamp = false)
            Transcript(text = raw.trim(), language = null, model = loaded?.displayName ?: "unknown")
        }
    }

    override suspend fun transcribeSamples(samples: FloatArray): String? {
        if (!available || samples.isEmpty()) return null
        return gate.partial {
            val ctx = ensureContext()
            ctx.transcribeData(samples, printTimestamp = false).trim()
        }
    }

    /**
     * Load the model once, or reload if the active model changed since. Always called
     * under [gate], so no extra lock. Throws if no model is resolvable (callers gate on
     * [available] first for committed decodes; partials pre-check).
     */
    private suspend fun ensureContext(): WhisperContext {
        val source = resolver.current()
            ?: error("No on-device model available; engine unavailable.")
        val existing = whisper
        if (existing != null && source == loaded) return existing

        // Switch (or first load): drop the old context before loading the new one.
        if (existing != null) {
            Log.i(TAG, "Switching model ${loaded?.displayName} → ${source.displayName}")
            runCatching { existing.release() }
            whisper = null
            loaded = null
        }
        Log.i(TAG, "Loading whisper model: ${source.displayName}")
        val ctx = when (source) {
            is ModelSource.DownloadedFile -> WhisperContext.createContextFromFile(source.path)
            is ModelSource.BundledAsset -> WhisperContext.createContextFromAsset(context.assets, source.assetPath)
        }
        whisper = ctx
        loaded = source
        return ctx
    }

    private companion object {
        const val TAG = "TuParles"
    }
}
