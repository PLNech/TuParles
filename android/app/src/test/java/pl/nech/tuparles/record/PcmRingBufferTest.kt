package pl.nech.tuparles.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch

/**
 * The tail buffer that feeds live partials (#42): it must return the most-recent window
 * oldest→newest, wrap correctly once full, and survive a reader snapshotting while the
 * mic thread writes. Pure JVM — no Android, no mic.
 */
class PcmRingBufferTest {

    private fun shorts(vararg v: Int) = ShortArray(v.size) { v[it].toShort() }

    @Test
    fun empty_buffer_snapshots_to_nothing() {
        val ring = PcmRingBuffer(4)
        assertEquals(0, ring.size())
        assertEquals(0, ring.snapshotFloats().size)
    }

    @Test
    fun below_capacity_keeps_everything_in_order() {
        val ring = PcmRingBuffer(8)
        ring.append(shorts(32767, -32768, 0), 3)

        assertEquals(3, ring.size())
        val f = ring.snapshotFloats()
        assertEquals(3, f.size)
        assertEquals(32767 / 32768f, f[0], 1e-6f)
        assertEquals(-1f, f[1], 1e-6f)
        assertEquals(0f, f[2], 1e-6f)
    }

    @Test
    fun honours_the_n_argument_ignoring_the_chunk_tail() {
        val ring = PcmRingBuffer(8)
        // A real read returns a fixed buffer with only the first n samples valid.
        ring.append(shorts(100, 200, 999, 999), 2)
        val f = ring.snapshotFloats()
        assertEquals(2, f.size)
        assertEquals(100 / 32768f, f[0], 1e-6f)
        assertEquals(200 / 32768f, f[1], 1e-6f)
    }

    @Test
    fun wraps_and_retains_only_the_most_recent_capacity_samples() {
        val ring = PcmRingBuffer(4)
        // Feed 1..6 across several appends; only the last 4 (3,4,5,6) survive, in order.
        ring.append(shorts(1, 2, 3), 3)
        ring.append(shorts(4, 5), 2)
        ring.append(shorts(6), 1)

        assertEquals(4, ring.size())
        val f = ring.snapshotFloats()
        val recovered = f.map { Math.round(it * 32768f) }
        assertEquals(listOf(3, 4, 5, 6), recovered)
    }

    @Test
    fun a_single_append_larger_than_capacity_keeps_the_tail() {
        val ring = PcmRingBuffer(3)
        ring.append(shorts(10, 20, 30, 40, 50), 5)
        assertEquals(3, ring.size())
        val recovered = ring.snapshotFloats().map { Math.round(it * 32768f) }
        assertEquals(listOf(30, 40, 50), recovered)
    }

    @Test
    fun clear_forgets_everything() {
        val ring = PcmRingBuffer(4)
        ring.append(shorts(1, 2, 3), 3)
        ring.clear()
        assertEquals(0, ring.size())
        assertEquals(0, ring.snapshotFloats().size)
    }

    @Test
    fun concurrent_writes_and_snapshots_stay_consistent() {
        // A writer thread streams a known ramp while the reader snapshots in a tight loop.
        // We don't assert an exact interleaving (that's inherently racy); we assert the
        // invariants that must ALWAYS hold — bounded size, in-range values — and that the
        // final settled snapshot is exactly the last `capacity` samples written.
        val capacity = 256
        val total = 100_000
        val ring = PcmRingBuffer(capacity)
        val started = CountDownLatch(1)

        val writer = Thread {
            started.countDown()
            var i = 1
            val chunk = ShortArray(64)
            while (i <= total) {
                var k = 0
                while (k < chunk.size && i <= total) {
                    chunk[k] = (i % 30000).toShort()
                    k++; i++
                }
                ring.append(chunk, k)
            }
        }

        writer.start()
        started.await()
        // Hammer snapshots concurrently; each one must be self-consistent.
        repeat(5_000) {
            val snap = ring.snapshotFloats()
            assertTrue("size ${snap.size} exceeds capacity", snap.size <= capacity)
            assertTrue(snap.all { it >= -1f && it <= 1f })
        }
        writer.join()

        // After the writer settles, the buffer holds exactly the last `capacity` values.
        val f = ring.snapshotFloats()
        assertEquals(capacity, f.size)
        val expected = (total - capacity + 1..total).map { (it % 30000).toShort() }
        val recovered = f.map { Math.round(it * 32768f).toShort() }
        assertEquals(expected, recovered)
    }
}
