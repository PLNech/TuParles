package pl.nech.tuparles.input

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DictationCommitTest {
    @Test
    fun emptyTextDoesNotCommit() {
        var called = false
        assertFalse(commitDictation({ called = true }, "   "))
        assertFalse(called)
    }

    @Test
    fun recognizeResultIsTheListAKeyboardReads() {
        assertEquals(null, recognizeSpeechResult("  "))
        assertEquals(arrayListOf("yo dawg"), recognizeSpeechResult(" yo dawg "))
    }

    @Test
    fun trimmedTextIsWhatLands() {
        var landed = ""
        assertTrue(commitDictation({ landed = it }, "  yo dawg  "))
        assertEquals("yo dawg", landed)
    }
}
