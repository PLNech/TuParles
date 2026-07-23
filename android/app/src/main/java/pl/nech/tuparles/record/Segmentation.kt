package pl.nech.tuparles.record

import kotlin.math.sqrt

/**
 * Where the rolling-committed transcript is cut. Segmentation is by silence, with
 * hysteresis so an ordinary breath does not fragment a sentence and a pause-free
 * speaker still commits before the recording ends.
 *
 * The defaults are a starting point, not gospel ("measure before you trust"): the
 * silence threshold in particular is mic-dependent (see the mic-level notes), so it is
 * a constant here, tunable in one place, and validated on-device against real takes.
 *
 * @param sampleRate         PCM sample rate (16 kHz — what the recorder and whisper use).
 * @param frameMs            analysis frame length; RMS + the voiced/silence decision are
 *                           per-frame, independent of the mic's chunk size.
 * @param rmsThreshold       normalised RMS ([0, 1]) below which a frame counts as silence.
 * @param minSilenceMs       continuous silence that closes a segment (~a sentence pause).
 * @param minSegmentMs       a silence-close is suppressed until the open segment is at
 *                           least this long, so a brief mid-sentence pause never cuts.
 * @param maxSegmentMs       hard cap: a pause-free speaker is committed at this length so
 *                           the durable transcript keeps growing during long monologues.
 */
data class SegmentationConfig(
    val sampleRate: Int = SAMPLE_RATE,
    val frameMs: Int = 30,
    val rmsThreshold: Float = 0.012f,
    val minSilenceMs: Int = 700,
    val minSegmentMs: Int = 3_000,
    val maxSegmentMs: Int = 30_000,
) {
    val frameSamples: Int get() = sampleRate * frameMs / 1000
    val minSilenceSamples: Int get() = sampleRate * minSilenceMs / 1000
    val minSegmentSamples: Int get() = sampleRate * minSegmentMs / 1000
    val maxSegmentSamples: Int get() = sampleRate * maxSegmentMs / 1000

    init {
        require(frameSamples > 0) { "frameMs too small for sampleRate" }
        require(minSegmentMs <= maxSegmentMs) { "minSegmentMs must not exceed maxSegmentMs" }
    }
}

/**
 * A completed, silence-bounded segment ready for a committed decode. [samples] are the
 * normalised floats ([-1, 1]) whisper.cpp wants; [startSample]/[endSample] locate it on
 * the recording's timeline so ordering and reconciliation stay deterministic.
 *
 * Segments are contiguous by construction — segment *i*'s [endSample] equals segment
 * *i+1*'s [startSample] — so concatenating their text loses nothing and duplicates
 * nothing, whatever the pause structure of the speech.
 */
class ClosedSegment(
    val index: Int,
    val startSample: Int,
    val endSample: Int,
    val samples: FloatArray,
) {
    val durationMs: Int get() = ((endSample - startSample).toLong() * 1000 / SAMPLE_RATE).toInt()
}

/**
 * Splits a live PCM16 stream into silence-bounded segments, purely and deterministically
 * — no Android, no coroutines, no clock — so the whole boundary policy is unit-testable
 * on the JVM. It is a *pure observer*: it never touches the WAV write path; a caller feeds
 * it the same chunks it writes, and recording is unaffected whether or not anyone reads back.
 *
 * The frame decision (voiced vs silence) is per fixed-length frame, independent of how the
 * mic hands over samples, so it behaves identically for 20 ms callbacks or 1 s ones. Frames
 * that straddle an [accept] boundary are carried over.
 */
class SilenceSegmenter(private val config: SegmentationConfig) {

    // The open segment's audio, retained until it closes (bounded by maxSegmentSamples).
    private var buffer = ShortArray(config.maxSegmentSamples.coerceAtLeast(config.frameSamples))
    private var bufLen = 0

    // Samples not yet forming a whole analysis frame, carried into the next accept().
    private val frameCarry = ShortArray(config.frameSamples)
    private var frameCarryLen = 0

    private var totalSamples = 0 // absolute count seen since construction
    private var segmentStart = 0 // absolute start of the open segment
    private var trailingSilence = 0 // consecutive silence samples at the tail of the open segment
    private var voicedInSegment = false // has the open segment held any speech?
    private var nextIndex = 0

    /** Feed [n] samples of [chunk]; returns any segments that closed on this input, in order. */
    fun accept(chunk: ShortArray, n: Int): List<ClosedSegment> {
        val take = n.coerceAtMost(chunk.size)
        if (take <= 0) return emptyList()
        var closed: MutableList<ClosedSegment>? = null

        var i = 0
        while (i < take) {
            // Fill one analysis frame (using any carried remainder first).
            val room = config.frameSamples - frameCarryLen
            val copy = minOf(room, take - i)
            System.arraycopy(chunk, i, frameCarry, frameCarryLen, copy)
            frameCarryLen += copy
            i += copy
            if (frameCarryLen < config.frameSamples) break // wait for more input

            val seg = ingestFrame(frameCarry, config.frameSamples)
            frameCarryLen = 0
            if (seg != null) (closed ?: mutableListOf<ClosedSegment>().also { closed = it }).add(seg)
        }
        return closed ?: emptyList()
    }

    /**
     * Close whatever is still open (the recording stopped): the remainder after the last
     * committed segment. Includes any sub-frame carry. Returns null when nothing is buffered.
     */
    fun flush(): ClosedSegment? {
        if (frameCarryLen > 0) {
            append(frameCarry, frameCarryLen)
            totalSamples += frameCarryLen
            frameCarryLen = 0
        }
        if (bufLen == 0) return null
        return closeSegment()
    }

    /** Process one full frame; returns a segment if this frame closed one. */
    private fun ingestFrame(frame: ShortArray, len: Int): ClosedSegment? {
        append(frame, len)
        totalSamples += len

        val voiced = rms(frame, len) >= config.rmsThreshold
        if (voiced) {
            voicedInSegment = true
            trailingSilence = 0
        } else {
            trailingSilence += len
        }

        val openLen = totalSamples - segmentStart
        val silenceClose = voicedInSegment &&
            openLen >= config.minSegmentSamples &&
            trailingSilence >= config.minSilenceSamples
        val capClose = openLen >= config.maxSegmentSamples
        return if (silenceClose || capClose) closeSegment() else null
    }

    /** Emit the open segment [segmentStart, totalSamples) and reset for the next one. */
    private fun closeSegment(): ClosedSegment {
        val out = FloatArray(bufLen)
        for (j in 0 until bufLen) out[j] = buffer[j] / 32768f
        val seg = ClosedSegment(nextIndex++, segmentStart, totalSamples, out)
        bufLen = 0
        segmentStart = totalSamples
        trailingSilence = 0
        voicedInSegment = false
        return seg
    }

    private fun append(src: ShortArray, len: Int) {
        if (bufLen + len > buffer.size) {
            var cap = buffer.size * 2
            while (cap < bufLen + len) cap *= 2
            buffer = buffer.copyOf(cap)
        }
        System.arraycopy(src, 0, buffer, bufLen, len)
        bufLen += len
    }

    private fun rms(frame: ShortArray, len: Int): Float {
        var sum = 0.0
        for (j in 0 until len) {
            val s = frame[j].toDouble()
            sum += s * s
        }
        return (sqrt(sum / len) / 32768.0).toFloat()
    }
}
