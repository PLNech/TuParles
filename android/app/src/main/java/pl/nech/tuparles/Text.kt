package pl.nech.tuparles

/**
 * Framework-free text helpers shared across surfaces. Kept Android-import-free on
 * purpose so they're unit-testable on a plain JVM (no Robolectric) — the first
 * tested seam of the Kotlin side.
 */

/**
 * Levenshtein edit distance — the learning signal's magnitude (shape, not content):
 * how far the user's correction moved from what the model said. Two-row DP, O(min)
 * space.
 */
fun levenshtein(a: String, b: String): Int {
    if (a == b) return 0
    if (a.isEmpty()) return b.length
    if (b.isEmpty()) return a.length
    var prev = IntArray(b.length + 1) { it }
    var cur = IntArray(b.length + 1)
    for (i in 1..a.length) {
        cur[0] = i
        for (j in 1..b.length) {
            val cost = if (a[i - 1] == b[j - 1]) 0 else 1
            cur[j] = minOf(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        }
        val tmp = prev; prev = cur; cur = tmp
    }
    return prev[b.length]
}

/** Human-readable byte size for the storage readouts (o / Ko / Mo). */
fun humanBytes(bytes: Long): String = when {
    bytes <= 0L -> "—"
    bytes < 1024 -> "$bytes o"
    bytes < 1024 * 1024 -> "${bytes / 1024} Ko"
    else -> "${"%.1f".format(bytes / 1024.0 / 1024.0)} Mo"
}
