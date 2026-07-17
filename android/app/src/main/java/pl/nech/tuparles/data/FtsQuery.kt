package pl.nech.tuparles.data

/**
 * Turns free-form user text into a safe FTS4 MATCH expression (issue #40, Phase C).
 *
 * We split on anything that is not a letter or digit, so the user's stray quotes,
 * hyphens and colons can never become FTS operators and blow up the query. Each token
 * gets a trailing `*` for prefix matching, so a search filters live as you type
 * ("bon" already matches "bonjour"). Tokens are implicitly AND-ed by FTS.
 *
 * Returns null when nothing is searchable (blank input, or only punctuation) — the
 * caller then shows the full note list instead of running an empty search.
 */
object FtsQuery {
    private val separators = Regex("[^\\p{L}\\p{N}]+")

    fun toMatch(raw: String): String? {
        val tokens = raw.split(separators).filter { it.isNotBlank() }
        if (tokens.isEmpty()) return null
        return tokens.joinToString(" ") { "$it*" }
    }
}
