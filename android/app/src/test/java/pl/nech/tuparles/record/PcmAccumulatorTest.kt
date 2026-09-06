package pl.nech.tuparles.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertArrayEquals
import org.junit.Test

/**
 * The whole-take PCM store (long dictation takes). What must hold: every sample survives
 * in order whatever the mic's chunk size, chunk boundaries are invisible to the caller,
 * and only the first `n` samples of a partly-filled mic buffer are taken. Pure JVM.
 */
class PcmAccumulatorTest {

    private fun shorts(vararg v: Int) = ShortArray(v.size) { v[it].toShort() }

    @Test
    fun empty_accumulator_yields_nothing() {
        val acc = PcmAccumulator(4)
        assertEquals(0, acc.size())
        assertEquals(0, acc.toShortArray().size)
    }

    @Test
    fun keeps_samples_in_order_within_one_chunk() {
        val acc = PcmAccumulator(8)
        acc.append(shorts(32767, -32768, 0), 3)

        assertEquals(3, acc.size())
        assertArrayEquals(shorts(32767, -32768, 0), acc.toShortArray())
    }

    @Test
    fun honours_the_n_argument_ignoring_the_chunk_tail() {
        val acc = PcmAccumulator(8)
        // A real mic read returns a fixed buffer with only the first n samples valid.
        acc.append(shorts(100, 200, 999, 999), 2)

        assertEquals(2, acc.size())
        assertArrayEquals(shorts(100, 200), acc.toShortArray())
    }

    @Test
    fun an_append_spanning_several_chunks_stays_contiguous() {
        val acc = PcmAccumulator(4)
        acc.append(shorts(1, 2, 3, 4, 5, 6, 7, 8, 9), 9)

        assertEquals(9, acc.size())
        assertArrayEquals(shorts(1, 2, 3, 4, 5, 6, 7, 8, 9), acc.toShortArray())
    }

    @Test
    fun appends_landing_exactly_on_a_chunk_boundary_add_no_padding() {
        val acc = PcmAccumulator(4)
        acc.append(shorts(1, 2, 3, 4), 4) // fills chunk 0 exactly
        assertEquals(4, acc.size())
        assertArrayEquals(shorts(1, 2, 3, 4), acc.toShortArray())

        acc.append(shorts(5), 1) // must open chunk 1, not pad chunk 0
        assertEquals(5, acc.size())
        assertArrayEquals(shorts(1, 2, 3, 4, 5), acc.toShortArray())
    }

    @Test
    fun many_ragged_appends_reassemble_exactly() {
        // Mic chunk sizes are not chunk-aligned; feed a known ramp in uneven pieces.
        val acc = PcmAccumulator(64)
        val total = 5_000
        var next = 1
        while (next <= total) {
            val n = minOf(((next * 7) % 23) + 1, total - next + 1)
            val chunk = ShortArray(n) { ((next + it) % 30_000).toShort() }
            acc.append(chunk, n)
            next += n
        }

        assertEquals(total, acc.size())
        val expected = ShortArray(total) { ((it + 1) % 30_000).toShort() }
        assertArrayEquals(expected, acc.toShortArray())
    }

    @Test
    fun clear_forgets_everything_and_the_next_take_starts_clean() {
        val acc = PcmAccumulator(4)
        acc.append(shorts(1, 2, 3, 4, 5), 5)
        acc.clear()

        assertEquals(0, acc.size())
        assertEquals(0, acc.toShortArray().size)

        acc.append(shorts(9, 8), 2)
        assertArrayEquals(shorts(9, 8), acc.toShortArray())
    }

    @Test
    fun samples_are_never_boxed_into_the_cache_range_only() {
        // Regression guard for the reason this class exists: values well outside
        // Short.valueOf's -128..127 cache must round-trip byte-exact, not merely fit.
        val acc = PcmAccumulator(3)
        val loud = shorts(-32768, -20000, -129, 128, 20000, 32767)
        acc.append(loud, loud.size)
        assertArrayEquals(loud, acc.toShortArray())
    }
}
