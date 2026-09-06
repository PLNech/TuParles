package pl.nech.tuparles.record

/**
 * Holds a whole take's PCM16 until stop, when the WAV is written once. A long dictation
 * lives here for its entire length, so the per-sample cost *is* the long-take feature:
 * 16-bit samples stay 16 bits — 2 B each.
 *
 * That is the point of this class. It replaces an `ArrayList<Short>`, which cost ~13.6 B
 * per sample: 4 B for the reference in the backing array, plus a heap-allocated
 * `java.lang.Short` (16 B on ART) for every sample outside `Short.valueOf`'s -128..127
 * cache — and at a 0.012 RMS speech threshold, voiced audio sits in the hundreds, so
 * nearly every sample missed that cache. A two-hour take cost ~2.5 GB there; it costs
 * ~230 MB here.
 *
 * Chunked rather than one growing array, deliberately: an append never reallocates or
 * copies what is already captured, so the mic thread never faces a doubling transient
 * (two multi-hundred-MB arrays live at once) or the GC storm that comes with it.
 *
 * Not synchronised, by the same discipline the recorder has always had: the mic reader
 * thread is the only writer, and [toShortArray] runs only after that thread is joined.
 */
class PcmAccumulator(private val chunkSamples: Int = DEFAULT_CHUNK_SAMPLES) {
    init {
        require(chunkSamples > 0) { "chunkSamples must be positive, was $chunkSamples" }
    }

    private val chunks = ArrayList<ShortArray>()
    private var count = 0

    /** Samples accumulated so far. */
    fun size(): Int = count

    /** Append the first [n] samples of [src] (a mic read fills only part of its buffer). */
    fun append(src: ShortArray, n: Int) {
        val take = n.coerceAtMost(src.size)
        if (take <= 0) return
        var done = 0
        while (done < take) {
            val used = count % chunkSamples
            if (used == 0) chunks.add(ShortArray(chunkSamples))
            val copy = minOf(chunkSamples - used, take - done)
            System.arraycopy(src, done, chunks[count / chunkSamples], used, copy)
            done += copy
            count += copy
        }
    }

    /** Forget everything (call at the start of a fresh recording). */
    fun clear() {
        chunks.clear()
        count = 0
    }

    /** The whole take as one contiguous array, oldest→newest. Empty when nothing captured. */
    fun toShortArray(): ShortArray {
        val out = ShortArray(count)
        var at = 0
        for (c in chunks) {
            val copy = minOf(c.size, count - at)
            if (copy <= 0) break
            System.arraycopy(c, 0, out, at, copy)
            at += copy
        }
        return out
    }

    private companion object {
        /** 512 Ki samples = 1 MB per chunk: incremental growth, ~110 chunks for a 2 h take. */
        const val DEFAULT_CHUNK_SAMPLES = 512 * 1024
    }
}
