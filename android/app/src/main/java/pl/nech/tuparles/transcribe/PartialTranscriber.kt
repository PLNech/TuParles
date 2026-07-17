package pl.nech.tuparles.transcribe

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.di.ApplicationScope
import pl.nech.tuparles.record.RecorderStateHolder
import javax.inject.Inject
import javax.inject.Singleton

/** Where a partial window comes from: the recent-audio tail, as normalised floats. */
fun interface PartialSource {
    fun snapshot(): FloatArray
}

/**
 * The live-partials loop of issue #42: while a note is being recorded, every ~5 s it
 * snapshots the last few seconds of audio and decodes them, publishing the text as an
 * ephemeral PARTIAL on [RecorderStateHolder]. This is reassurance ("the mic hears me"),
 * not a running transcript — the durable text is still the post-hoc decode of the WAV.
 *
 * Three doctrines are baked in:
 *  - **Self-pacing, never queued**: the next window only starts after the previous decode
 *    returns. A slow device produces fewer partials, never a backlog.
 *  - **Yields to committed work**: decoding goes through the engine's partial path, which
 *    skips (returns null) when a committed post-hoc decode holds the engine.
 *  - **Never harms the recording**: a partial failure is swallowed (logged); repeated
 *    failures stop the loop. The mic, the WAV and the final decode are untouched.
 *
 * Graceful degradation (house doctrine, mobile edition): no engine / no model →
 * [TranscriptionEngine.supportsPartials] is false → [start] is a no-op and recording
 * proceeds exactly as before.
 */
@Singleton
class PartialTranscriber @Inject constructor(
    private val engine: TranscriptionEngine,
    private val stateHolder: RecorderStateHolder,
    @ApplicationScope private val scope: CoroutineScope,
) {
    @Volatile private var job: Job? = null

    /** Begin the loop against [source]. No-op if the engine can't do partials. */
    fun start(source: PartialSource) {
        if (!engine.supportsPartials) return
        stop() // cancel any prior loop; also clears stale partial text
        job = scope.launch {
            var failures = 0
            while (isActive) {
                delay(INTERVAL_MS)
                val samples = source.snapshot()
                if (samples.isEmpty()) continue
                try {
                    val text = engine.transcribeSamples(samples)
                    failures = 0 // a null (busy-skip) is not a failure, just no update
                    if (!text.isNullOrBlank()) stateHolder.setPartial(text.trim())
                } catch (e: Throwable) {
                    Log.w(TAG, "partial decode failed (recording unaffected)", e)
                    if (++failures >= MAX_FAILURES) {
                        Log.w(TAG, "too many partial failures; stopping the partials loop")
                        break
                    }
                }
            }
        }
    }

    /** Stop the loop and clear the partial text (the final transcript is the durable one). */
    fun stop() {
        job?.cancel()
        job = null
        stateHolder.clearPartial()
    }

    private companion object {
        const val TAG = "TuParles"
        const val INTERVAL_MS = 5_000L
        const val MAX_FAILURES = 3
    }
}
