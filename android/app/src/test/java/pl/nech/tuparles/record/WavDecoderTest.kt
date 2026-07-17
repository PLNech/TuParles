package pl.nech.tuparles.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs

/**
 * The WAV round-trip that feeds whisper.cpp: [writeWav] then [decodeWavToFloats] must
 * recover the same signal, normalised to [-1, 1]. Pure JVM — proves the audio path
 * off-device even though the native decode itself can only run on the phone.
 */
class WavDecoderTest {

    @Test
    fun roundtrips_pcm16_to_normalised_floats() {
        val pcm = shortArrayOf(0, 16384, -16384, Short.MAX_VALUE, Short.MIN_VALUE, 1000, -1000)
        val tmp = File.createTempFile("tuparles-test", ".wav")
        try {
            writeWav(tmp, pcm)
            val floats = decodeWavToFloats(tmp)

            assertEquals(pcm.size, floats.size)
            for (i in pcm.indices) {
                assertEquals(pcm[i] / 32768f, floats[i], 1e-6f)
            }
            // All samples land inside the range whisper expects.
            assertTrue(floats.all { it >= -1f && it <= 1f })
        } finally {
            tmp.delete()
        }
    }

    @Test
    fun tolerates_empty_recording() {
        val tmp = File.createTempFile("tuparles-empty", ".wav")
        try {
            writeWav(tmp, ShortArray(0))
            assertEquals(0, decodeWavToFloats(tmp).size)
        } finally {
            tmp.delete()
        }
    }

    @Test
    fun preserves_sample_magnitude_ordering() {
        // A louder sample must decode to a larger magnitude — no sign/scale surprises.
        val pcm = shortArrayOf(100, 20000)
        val tmp = File.createTempFile("tuparles-mag", ".wav")
        try {
            writeWav(tmp, pcm)
            val f = decodeWavToFloats(tmp)
            assertTrue(abs(f[1]) > abs(f[0]))
        } finally {
            tmp.delete()
        }
    }
}
