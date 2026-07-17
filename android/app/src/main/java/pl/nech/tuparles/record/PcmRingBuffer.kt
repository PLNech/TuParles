package pl.nech.tuparles.record

/**
 * A fixed-capacity ring of the most recent PCM16 samples, kept alongside the WAV write
 * so the live-partials loop (#42) can peek at the last few seconds of audio without a
 * temp WAV. Older samples are overwritten once full; a snapshot returns the retained
 * window oldest→newest, normalised to the floats whisper.cpp wants ([-1, 1]).
 *
 * Thread-safe: the mic reader thread [append]s while a partials coroutine [snapshotFloats]s.
 * Both paths are cheap and lock only briefly, so writing here never disturbs recording —
 * and a recorder that never snapshots pays only the array copy of [append].
 */
class PcmRingBuffer(private val capacity: Int) {
    init {
        require(capacity > 0) { "capacity must be positive, was $capacity" }
    }

    private val ring = ShortArray(capacity)
    private var writePos = 0
    private var count = 0
    private val lock = Any()

    /** Append the first [n] samples of [chunk] (n may exceed capacity; only the tail survives). */
    fun append(chunk: ShortArray, n: Int) {
        val take = n.coerceAtMost(chunk.size)
        if (take <= 0) return
        synchronized(lock) {
            for (i in 0 until take) {
                ring[writePos] = chunk[i]
                writePos = (writePos + 1) % capacity
                if (count < capacity) count++
            }
        }
    }

    /** Forget everything (call at the start of a fresh recording). */
    fun clear() {
        synchronized(lock) {
            writePos = 0
            count = 0
        }
    }

    /** Number of samples currently retained (0..capacity). */
    fun size(): Int = synchronized(lock) { count }

    /** The retained window, oldest→newest, normalised to [-1, 1]. Empty when nothing buffered. */
    fun snapshotFloats(): FloatArray {
        val snap: ShortArray
        val n: Int
        val start: Int
        synchronized(lock) {
            n = count
            if (n == 0) return FloatArray(0)
            // Oldest retained sample sits `count` positions behind the write head.
            start = ((writePos - count) % capacity + capacity) % capacity
            snap = ring.copyOf()
        }
        val out = FloatArray(n)
        for (i in 0 until n) {
            out[i] = snap[(start + i) % capacity] / 32768f
        }
        return out
    }
}
