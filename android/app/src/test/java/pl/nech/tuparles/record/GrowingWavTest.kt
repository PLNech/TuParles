package pl.nech.tuparles.record

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** A spill file stays a readable WAV after every append, including a close mid-take. */
class GrowingWavTest {

    @Test
    fun appends_stay_readable_and_match_the_samples() {
        val file = File.createTempFile("growing", ".wav")
        val first = shortArrayOf(1, 2, 3)
        val second = shortArrayOf(4, 5)
        GrowingWav(file).use { wav ->
            wav.append(first, first.size)
            assertEquals(3, wavSampleCount(file))
            wav.append(second, second.size)
        }
        assertEquals(5, wavSampleCount(file))
        val decoded = decodeWavToFloats(file)
        assertEquals(5, decoded.size)
        assertEquals(1 / 32768f, decoded[0], 1e-6f)
        assertEquals(5 / 32768f, decoded[4], 1e-6f)
        file.delete()
    }

    @Test
    fun a_header_only_file_counts_as_no_samples() {
        val file = File.createTempFile("growing-empty", ".wav")
        GrowingWav(file).close()
        assertEquals(0, wavSampleCount(file))
        file.delete()
    }
}
