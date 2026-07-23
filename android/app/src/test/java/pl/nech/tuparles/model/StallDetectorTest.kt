package pl.nech.tuparles.model

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The stall watchdog: pure, driven by a fake clock — no sleeps, no Android. */
class StallDetectorTest {

    /** A clock the test advances by hand. */
    private class FakeClock(var t: Long = 0L) : () -> Long {
        override fun invoke(): Long = t
    }

    @Test
    fun no_progress_past_the_threshold_is_stalled() {
        val clock = FakeClock()
        val d = StallDetector(stallThresholdMs = 15_000L, now = clock)

        clock.t = 0L
        assertFalse("first observation is never stalled", d.isStalled(0L))
        clock.t = 10_000L
        assertFalse("under threshold", d.isStalled(0L))
        clock.t = 15_000L
        assertTrue("15s of zero bytes = stalled", d.isStalled(0L))
    }

    @Test
    fun forward_progress_resets_the_clock() {
        val clock = FakeClock()
        val d = StallDetector(stallThresholdMs = 15_000L, now = clock)

        clock.t = 0L; d.isStalled(0L)
        clock.t = 14_000L; assertFalse(d.isStalled(0L))
        // Bytes moved at t=14s → the clock resets to 14s.
        clock.t = 14_000L; assertFalse(d.isStalled(1_000L))
        clock.t = 28_000L; assertFalse("only 14s since last progress", d.isStalled(1_000L))
        clock.t = 29_001L; assertTrue("now 15s+ since the last byte", d.isStalled(1_000L))
    }

    @Test
    fun a_download_that_keeps_moving_is_never_stalled() {
        val clock = FakeClock()
        val d = StallDetector(stallThresholdMs = 1_000L, now = clock)
        var bytes = 0L
        for (step in 0..100) {
            clock.t = step * 10_000L // huge gaps, but bytes always advance
            bytes += 1
            assertFalse("progress each poll keeps it alive", d.isStalled(bytes))
        }
    }
}
