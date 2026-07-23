package pl.nech.tuparles.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The silence-hysteresis segmenter (rolling-committed transcript). Pure JVM, synthetic PCM:
 * loud frames stand in for speech, zeros for silence. Asserts the boundary policy — min
 * segment length, min silence to close, the max-segment cap, contiguity (no gaps / no
 * overlaps), and correct behaviour across [accept] chunk boundaries.
 */
class SilenceSegmenterTest {

    private val config = SegmentationConfig(
        sampleRate = 16_000,
        frameMs = 30,
        rmsThreshold = 0.05f,
        minSilenceMs = 700,
        minSegmentMs = 3_000,
        maxSegmentMs = 30_000,
    )

    /** A loud (voiced) buffer of [ms] milliseconds — half-scale sine-ish constant. */
    private fun voiced(ms: Int): ShortArray = ShortArray(config.sampleRate * ms / 1000) { 8_000 }

    /** A silent buffer of [ms] milliseconds. */
    private fun silence(ms: Int): ShortArray = ShortArray(config.sampleRate * ms / 1000)

    private fun feed(seg: SilenceSegmenter, buf: ShortArray) = seg.accept(buf, buf.size)

    @Test
    fun brief_pause_does_not_cut_even_a_long_enough_segment() {
        val seg = SilenceSegmenter(config)
        // > minSegment of speech, then a 0.3 s pause (< minSilence): must NOT close — proving
        // it is the *silence length*, not the segment length, gating the cut here.
        assertTrue(feed(seg, voiced(2_000)).isEmpty())
        assertTrue(feed(seg, silence(300)).isEmpty())
        assertTrue(feed(seg, voiced(2_000)).isEmpty())
        // Now a full pause closes it: same segment, gated only on silence duration.
        assertEquals(1, feed(seg, silence(800)).size)
    }

    @Test
    fun a_sentence_pause_after_enough_speech_closes_one_segment() {
        val seg = SilenceSegmenter(config)
        feed(seg, voiced(4_000)) // > minSegment
        val closed = feed(seg, silence(800)) // > minSilence
        assertEquals(1, closed.size)
        val s = closed[0]
        assertEquals(0, s.index)
        assertEquals(0, s.startSample)
        // Closed once the silence threshold is crossed: ~4 s speech + ~0.7 s silence.
        assertTrue("segment spans the speech plus the closing silence", s.endSample >= config.sampleRate * 4)
        assertTrue(s.samples.isNotEmpty())
    }

    @Test
    fun silence_before_min_segment_does_not_close() {
        val seg = SilenceSegmenter(config)
        // Only 1 s of speech (< 3 s minSegment), then a long silence: must NOT close yet.
        feed(seg, voiced(1_000))
        val closed = feed(seg, silence(1_500))
        assertTrue("too-short a segment is not cut even on a long pause", closed.isEmpty())
    }

    @Test
    fun pure_silence_never_closes_a_segment_mid_stream() {
        val seg = SilenceSegmenter(config)
        // Silence alone (no voiced frame) never trips the silence-close: nothing to commit.
        val closed = feed(seg, silence(5_000))
        assertTrue(closed.isEmpty())
    }

    @Test
    fun max_segment_cap_closes_a_pause_free_speaker() {
        val seg = SilenceSegmenter(config)
        // 35 s of unbroken speech: the 30 s cap forces a commit mid-stream.
        val closed = feed(seg, voiced(35_000))
        assertEquals(1, closed.size)
        val s = closed[0]
        assertEquals(config.maxSegmentSamples, s.endSample - s.startSample)
    }

    @Test
    fun segments_are_contiguous_no_gaps_no_overlaps() {
        val seg = SilenceSegmenter(config)
        val all = mutableListOf<ClosedSegment>()
        // speech / pause / speech / pause / speech
        all += feed(seg, voiced(4_000))
        all += feed(seg, silence(800))
        all += feed(seg, voiced(4_000))
        all += feed(seg, silence(800))
        all += feed(seg, voiced(4_000))
        seg.flush()?.let { all += it }

        assertTrue("expected at least two committed segments plus a remainder", all.size >= 2)
        // End of each segment is the start of the next: the timeline is fully covered.
        for (k in 1 until all.size) {
            assertEquals(all[k - 1].endSample, all[k].startSample)
        }
        assertEquals("first segment starts at 0", 0, all.first().startSample)
    }

    @Test
    fun flush_returns_the_open_remainder_after_the_last_close() {
        val seg = SilenceSegmenter(config)
        feed(seg, voiced(4_000))
        val closed = feed(seg, silence(800)) // closes segment 0
        assertEquals(1, closed.size)
        feed(seg, voiced(2_000)) // an open, un-closed tail
        val remainder = seg.flush()
        assertNotNull(remainder)
        assertEquals(1, remainder!!.index)
        assertEquals(closed[0].endSample, remainder.startSample)
    }

    @Test
    fun flush_on_empty_is_null() {
        assertNull(SilenceSegmenter(config).flush())
    }

    @Test
    fun frame_decision_is_independent_of_accept_chunk_size() {
        // Feed the same audio one frame at a time vs one big buffer: identical boundaries.
        val whole = SilenceSegmenter(config)
        val wholeClosed = mutableListOf<ClosedSegment>()
        wholeClosed += feed(whole, voiced(4_000))
        wholeClosed += feed(whole, silence(800))

        val drip = SilenceSegmenter(config)
        val dripClosed = mutableListOf<ClosedSegment>()
        val speech = voiced(4_000)
        val pause = silence(800)
        // 10 ms drips — smaller than a 30 ms frame, exercising the carry path.
        val step = config.sampleRate * 10 / 1000
        for (buf in listOf(speech, pause)) {
            var off = 0
            while (off < buf.size) {
                val len = minOf(step, buf.size - off)
                dripClosed += drip.accept(buf.copyOfRange(off, off + len), len)
                off += len
            }
        }
        assertEquals(wholeClosed.size, dripClosed.size)
        assertEquals(wholeClosed[0].endSample, dripClosed[0].endSample)
    }

    @Test
    fun long_recording_commits_many_segments_progressively() {
        val seg = SilenceSegmenter(config)
        var count = 0
        // Five "sentences", each 4 s speech + 0.8 s pause.
        repeat(5) {
            feed(seg, voiced(4_000))
            count += feed(seg, silence(800)).size
        }
        assertEquals("each sentence-pause commits one segment during recording", 5, count)
    }
}
