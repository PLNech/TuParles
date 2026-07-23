package pl.nech.tuparles.model

import java.io.File
import java.io.InputStream
import java.io.InterruptedIOException

/**
 * The byte-pump at the heart of the direct-HTTP download fallback, kept as pure
 * `java.io` so it is unit-tested with a `ByteArrayInputStream` and a temp file — no
 * socket, no Android. It streams an input to a destination file in bounded buffers
 * (never the whole model in heap), reports progress on a throttle, and bails promptly
 * when the caller signals cancellation (deleting the partial is the caller's job).
 *
 * @param progressBytes emit progress at least every this many bytes copied.
 * @param progressMs …or at least this often in wall time, whichever comes first.
 * @param now time source (injected so the time throttle is testable with a fake clock).
 */
class HttpStreamCopier(
    private val progressBytes: Long = 512L * 1024L,
    private val progressMs: Long = 400L,
    private val now: () -> Long = System::currentTimeMillis,
) {

    /**
     * Copy all of [input] into [dest], invoking [onProgress] with the running byte total
     * on the throttle (and once more at the end). Checks [isCancelled] before every read
     * and throws [InterruptedIOException] if it trips. Returns the total bytes written.
     */
    fun copy(
        input: InputStream,
        dest: File,
        isCancelled: () -> Boolean,
        onProgress: (Long) -> Unit,
    ): Long {
        dest.parentFile?.mkdirs()
        var total = 0L
        var lastReportBytes = 0L
        var lastReportAt = now()
        val buf = ByteArray(1 shl 16)
        dest.outputStream().use { out ->
            while (true) {
                if (isCancelled()) throw InterruptedIOException("download cancelled")
                val n = input.read(buf)
                if (n < 0) break
                out.write(buf, 0, n)
                total += n
                val t = now()
                if (total - lastReportBytes >= progressBytes || t - lastReportAt >= progressMs) {
                    onProgress(total)
                    lastReportBytes = total
                    lastReportAt = t
                }
            }
        }
        onProgress(total)
        return total
    }
}
