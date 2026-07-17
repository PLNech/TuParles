package pl.nech.tuparles.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TranscriptSnippetTest {

    @Test
    fun short_transcript_returned_whole_no_ellipsis() {
        val s = TranscriptSnippet.around("Bonjour le monde", "monde")
        assertEquals("Bonjour le monde", s)
    }

    @Test
    fun long_transcript_centres_on_match_with_ellipses() {
        val text = "un ".repeat(30) + "cible " + "deux ".repeat(30)
        val s = TranscriptSnippet.around(text.trim(), "cible", radius = 20)
        assertTrue("keeps the match", s.contains("cible"))
        assertTrue("trims the head", s.startsWith("… "))
        assertTrue("trims the tail", s.endsWith(" …"))
    }

    @Test
    fun match_near_start_has_no_leading_ellipsis() {
        val text = "cible " + "mot ".repeat(40)
        val s = TranscriptSnippet.around(text.trim(), "cible", radius = 20)
        assertTrue(s.startsWith("cible"))
        assertTrue(s.endsWith(" …"))
    }

    @Test
    fun prefix_token_matches_partial_word() {
        val s = TranscriptSnippet.around("je parle de transcription locale", "transc")
        assertTrue(s.contains("transcription"))
    }

    @Test
    fun does_not_cut_mid_word() {
        val text = "aaaa bbbb cccc cible dddd eeee ffff"
        val s = TranscriptSnippet.around(text, "cible", radius = 6)
        // Every whitespace-separated chunk in the snippet (bar ellipses) is a whole word.
        s.replace("…", "").trim().split(" ").filter { it.isNotBlank() }.forEach { word ->
            assertTrue("'$word' should be a whole word", text.contains(word))
        }
    }

    @Test
    fun blank_query_returns_head_of_text() {
        val s = TranscriptSnippet.around("Bonjour le monde", "")
        assertEquals("Bonjour le monde", s)
    }
}
