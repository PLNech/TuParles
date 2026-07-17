package pl.nech.tuparles.util

import org.junit.Assert.assertEquals
import org.junit.Test

class FormatTest {

    @Test
    fun duration_formats_as_minutes_seconds() {
        assertEquals("0:00", Format.duration(0f))
        assertEquals("0:05", Format.duration(5f))
        assertEquals("0:05", Format.duration(5.9f)) // truncates, never rounds up
        assertEquals("0:59", Format.duration(59f))
        assertEquals("1:00", Format.duration(60f))
        assertEquals("1:23", Format.duration(83f))
        assertEquals("61:01", Format.duration(3661f)) // no hours: minutes just keep counting
    }

    @Test
    fun duration_clamps_negative_to_zero() {
        assertEquals("0:00", Format.duration(-3f))
    }

    @Test
    fun wavFileName_is_stable_for_a_timestamp() {
        assertEquals("note_1700000000000.wav", Format.wavFileName(1_700_000_000_000L))
        assertEquals("note_0.wav", Format.wavFileName(0L))
    }
}
