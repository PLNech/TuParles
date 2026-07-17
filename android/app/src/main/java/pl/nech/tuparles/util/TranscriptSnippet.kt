package pl.nech.tuparles.util

import pl.nech.tuparles.data.FtsQuery

/** Builds the search-result excerpt shown under a matching note. Pure, so it's unit-tested. */
object TranscriptSnippet {

    /**
     * A short excerpt of [transcript] centred on the first word that matches any token in
     * [query], with ellipses where the text is trimmed and word boundaries respected (never
     * cut mid-word). Falls back to the head of the transcript when nothing matches — which
     * shouldn't happen for a genuine hit, but keeps the UI graceful either way.
     */
    fun around(transcript: String, query: String, radius: Int = 40): String {
        val text = transcript.trim()
        val tokens = FtsQuery.toMatch(query)
            ?.split(" ")
            ?.map { it.removeSuffix("*").lowercase() }
            ?: return text
        val lower = text.lowercase()
        val hit = tokens.mapNotNull { t -> lower.indexOf(t).takeIf { it >= 0 } }.minOrNull()
            ?: return text.take(radius * 2).let { if (it.length < text.length) "$it …" else it }

        var start = (hit - radius).coerceAtLeast(0)
        var end = (hit + radius).coerceAtMost(text.length)
        while (start > 0 && !text[start - 1].isWhitespace()) start--
        while (end < text.length && !text[end].isWhitespace()) end++

        val body = text.substring(start, end).trim()
        val prefix = if (start > 0) "… " else ""
        val suffix = if (end < text.length) " …" else ""
        return "$prefix$body$suffix"
    }
}
