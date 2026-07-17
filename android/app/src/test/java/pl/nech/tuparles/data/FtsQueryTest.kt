package pl.nech.tuparles.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FtsQueryTest {

    @Test
    fun single_token_gets_prefix_star() {
        assertEquals("bonjour*", FtsQuery.toMatch("bonjour"))
    }

    @Test
    fun multiple_tokens_are_anded_with_prefix() {
        assertEquals("salut*", FtsQuery.toMatch(" salut "))
        assertEquals("code*", FtsQuery.toMatch("code"))
        assertEquals("bon*", FtsQuery.toMatch("bon"))
    }

    @Test
    fun words_split_on_non_alphanumerics_each_get_a_star() {
        assertEquals("code*", FtsQuery.toMatch("code"))
        assertEquals("hello*", FtsQuery.toMatch("hello"))
    }

    @Test
    fun keeps_letters_and_digits_across_scripts() {
        // Accented and non-latin letters are preserved (Fr-En code-switch tool).
        assertEquals("café*", FtsQuery.toMatch("café"))
        assertEquals("été*", FtsQuery.toMatch("été"))
    }

    @Test
    fun several_words_join_with_space() {
        assertEquals("bon*", FtsQuery.toMatch("bon"))
        assertEquals("hello* world*", FtsQuery.toMatch("hello world"))
        assertEquals("un* deux* trois*", FtsQuery.toMatch("un, deux; trois!"))
    }

    @Test
    fun fts_operators_and_quotes_are_neutralised_not_forwarded() {
        // Stray quotes / colons / hyphens must never reach FTS as operators.
        assertEquals("foo* bar*", FtsQuery.toMatch("\"foo\" - bar:"))
        assertEquals("a* b*", FtsQuery.toMatch("a* ^ b"))
    }

    @Test
    fun blank_or_punctuation_only_is_null() {
        assertNull(FtsQuery.toMatch(""))
        assertNull(FtsQuery.toMatch("   "))
        assertNull(FtsQuery.toMatch("--  ,;:"))
        assertNull(FtsQuery.toMatch("*"))
    }
}
