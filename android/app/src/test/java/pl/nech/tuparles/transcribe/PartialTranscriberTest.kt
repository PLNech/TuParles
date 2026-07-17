package pl.nech.tuparles.transcribe

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import pl.nech.tuparles.core.Transcript
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecorderStateHolder

/**
 * The live-partials loop (#42): pacing (self-paced, never queued), publishing into the
 * shared state, and graceful degradation when the engine can't do partials. Virtual
 * clock, fake engine — no device, no mic, deterministic.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PartialTranscriberTest {

    /** Matches PartialTranscriber.INTERVAL_MS. */
    private val interval = 5_000L

    private class FakeEngine(
        override val supportsPartials: Boolean = true,
        private val behaviour: suspend (FloatArray) -> String? = { "bonjour le monde" },
    ) : TranscriptionEngine {
        override val available: Boolean = true
        var calls = 0
        override suspend fun transcribe(wavPath: String): Transcript =
            throw UnsupportedOperationException("not used in partials tests")

        override suspend fun transcribeSamples(samples: FloatArray): String? {
            calls++
            return behaviour(samples)
        }
    }

    private class FakeSource(private val data: FloatArray = floatArrayOf(0.1f, 0.2f, 0.3f)) : PartialSource {
        var calls = 0
        override fun snapshot(): FloatArray {
            calls++
            return data
        }
    }

    @Test
    fun no_op_and_no_partials_when_engine_does_not_support_them() = runTest {
        val engine = FakeEngine(supportsPartials = false)
        val holder = RecorderStateHolder()
        holder.set(RecorderState.Recording(0L, 0f))
        val source = FakeSource()
        val pt = PartialTranscriber(engine, holder, backgroundScope)

        pt.start(source)
        advanceTimeBy(interval * 4)
        runCurrent()

        assertEquals(0, source.calls) // source never even sampled
        assertEquals(0, engine.calls)
        assertNull(holder.partial.value)
    }

    @Test
    fun publishes_decoded_text_as_a_partial_each_window() = runTest {
        val engine = FakeEngine()
        val holder = RecorderStateHolder()
        holder.set(RecorderState.Recording(0L, 0f))
        val pt = PartialTranscriber(engine, holder, backgroundScope)

        pt.start(FakeSource())
        advanceTimeBy(interval + 1)
        runCurrent()

        assertEquals(1, engine.calls)
        assertEquals("bonjour le monde", holder.partial.value)

        // Two more windows land as time advances.
        advanceTimeBy(interval * 2)
        runCurrent()
        assertEquals(3, engine.calls)

        pt.stop()
    }

    @Test
    fun self_paces_never_queuing_a_second_decode_while_one_is_in_flight() = runTest {
        // The engine blocks on the first window; time keeps advancing. A queued design
        // would fire more decodes — self-pacing must not: the next window waits for this one.
        val blocked = CompletableDeferred<Unit>()
        val engine = FakeEngine { blocked.await(); "late" }
        val holder = RecorderStateHolder()
        holder.set(RecorderState.Recording(0L, 0f))
        val pt = PartialTranscriber(engine, holder, backgroundScope)

        pt.start(FakeSource())
        advanceTimeBy(interval * 5) // five windows' worth of wall-clock
        runCurrent()

        assertEquals("only the in-flight decode; no backlog", 1, engine.calls)
        assertNull(holder.partial.value) // it never returned, so nothing was published
        pt.stop() // cancels the parked decode
    }

    @Test
    fun stop_cancels_the_loop_and_clears_the_partial() = runTest {
        val engine = FakeEngine()
        val holder = RecorderStateHolder()
        holder.set(RecorderState.Recording(0L, 0f))
        val pt = PartialTranscriber(engine, holder, backgroundScope)

        pt.start(FakeSource())
        advanceTimeBy(interval + 1)
        runCurrent()
        assertEquals("bonjour le monde", holder.partial.value)

        pt.stop()
        assertNull(holder.partial.value)

        val before = engine.calls
        advanceTimeBy(interval * 3)
        runCurrent()
        assertEquals("no decodes after stop", before, engine.calls)
    }

    @Test
    fun repeated_failures_stop_the_loop_and_never_touch_the_partial() = runTest {
        val engine = FakeEngine { error("decode boom") }
        val holder = RecorderStateHolder()
        holder.set(RecorderState.Recording(0L, 0f))
        val pt = PartialTranscriber(engine, holder, backgroundScope)

        pt.start(FakeSource())
        // Three failures (MAX_FAILURES) break the loop.
        advanceTimeBy(interval * 3 + 1)
        runCurrent()
        assertEquals(3, engine.calls)
        assertNull(holder.partial.value)

        // The loop is gone — further time yields no more attempts.
        advanceTimeBy(interval * 5)
        runCurrent()
        assertEquals(3, engine.calls)
    }
}
