package pl.nech.tuparles

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The first tests on the Kotlin side — pure-JVM, no Android framework, no Robolectric.
 * They cover the framework-free helpers in Text.kt (the learning-signal magnitude and
 * the storage readout), the seams most worth pinning because the learning loop and the
 * data-management UI both depend on them being exactly right.
 */
class TextTest {

    @Test fun levenshtein_identical_is_zero() {
        assertEquals(0, levenshtein("", ""))
        assertEquals(0, levenshtein("pipeline", "pipeline"))
    }

    @Test fun levenshtein_empty_is_other_length() {
        assertEquals(5, levenshtein("", "hello"))
        assertEquals(5, levenshtein("hello", ""))
    }

    @Test fun levenshtein_known_distances() {
        assertEquals(1, levenshtein("kitten", "kittens"))      // one insertion
        assertEquals(3, levenshtein("kitten", "sitting"))      // the classic
        assertEquals(1, levenshtein("a", "b"))                 // one substitution
        assertEquals(2, levenshtein("ab", "ba"))               // two substitutions (no transposition op)
    }

    @Test fun levenshtein_is_symmetric() {
        assertEquals(levenshtein("réglages", "reglage"), levenshtein("reglage", "réglages"))
    }

    @Test fun levenshtein_unicode_accents_count() {
        // a missed accent is a single-char substitution — the signal we want to see
        assertEquals(1, levenshtein("café", "cafe"))
    }

    @Test fun humanBytes_thresholds() {
        assertEquals("—", humanBytes(0))
        assertEquals("—", humanBytes(-5))
        assertEquals("512 o", humanBytes(512))
        assertEquals("1 Ko", humanBytes(1024))
        assertEquals("2 Ko", humanBytes(2048))
        assertEquals("1.0 Mo", humanBytes(1024L * 1024L))
        assertEquals("1.5 Mo", humanBytes(1024L * 1024L * 3 / 2))
    }
}
