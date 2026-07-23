package pl.nech.tuparles.util

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Small, pure formatting helpers — no Android, so they're unit-tested directly. */
object Format {

    /** Duration as `m:ss` — 5s → "0:05", 83s → "1:23", 3661s → "61:01". */
    fun duration(seconds: Float): String {
        val total = seconds.toInt().coerceAtLeast(0)
        return "%d:%02d".format(Locale.ROOT, total / 60, total % 60)
    }

    /** Stable WAV filename for a note captured at [createdAt] (epoch millis). */
    fun wavFileName(createdAt: Long): String = "note_$createdAt.wav"

    /** Size in whole mebibytes, French unit — 32_152_673 → "31 Mo", 0 → "0 Mo". */
    fun megabytes(bytes: Long): String {
        val mb = if (bytes <= 0L) 0L else (bytes + MB / 2) / MB
        return "%d Mo".format(Locale.ROOT, mb)
    }

    private const val MB = 1024L * 1024L

    /** Human date for the list row (formatter built per-call: SimpleDateFormat isn't thread-safe). */
    fun timestamp(createdAt: Long): String =
        SimpleDateFormat("d MMM yyyy · HH:mm", Locale.getDefault()).format(Date(createdAt))
}
