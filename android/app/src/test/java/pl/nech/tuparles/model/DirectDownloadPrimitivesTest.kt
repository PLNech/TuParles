package pl.nech.tuparles.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.InterruptedIOException

/**
 * The pure pieces of the direct-HTTP fallback — the byte-pump ([HttpStreamCopier]) and
 * redirect resolution ([HttpRedirect]) — exercised with a local test double instead of a
 * socket, so progress / cancel / redirect handling are covered without touching the network.
 */
class DirectDownloadPrimitivesTest {

    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun copier_streams_all_bytes_and_reports_a_final_total() {
        val data = ByteArray(300_000) { (it % 251).toByte() }
        val dest = tmp.newFile("out.bin")
        val progress = mutableListOf<Long>()
        // Small throttle so we see intermediate callbacks; time throttle off (fixed clock).
        val copier = HttpStreamCopier(progressBytes = 100_000L, progressMs = Long.MAX_VALUE, now = { 0L })

        val total = copier.copy(
            input = ByteArrayInputStream(data),
            dest = dest,
            isCancelled = { false },
            onProgress = { progress.add(it) },
        )

        assertEquals(300_000L, total)
        assertEquals("bytes landed on disk", 300_000L, dest.length())
        assertTrue("progress emitted at least a couple of times", progress.size >= 2)
        assertEquals("last progress equals the total", 300_000L, progress.last())
        assertTrue("progress is monotonic", progress.zipWithNext().all { (a, b) -> b >= a })
    }

    @Test
    fun copier_bails_promptly_when_cancelled() {
        val data = ByteArray(1_000_000)
        val dest = tmp.newFile("out.bin")
        val copier = HttpStreamCopier(now = { 0L })

        assertThrows(InterruptedIOException::class.java) {
            copier.copy(
                input = ByteArrayInputStream(data),
                dest = dest,
                isCancelled = { true }, // cancelled before the first read
                onProgress = {},
            )
        }
    }

    @Test
    fun redirect_follows_https_absolute_and_relative_targets() {
        assertTrue(HttpRedirect.isRedirect(302))
        assertTrue(HttpRedirect.isRedirect(301))
        assertEquals(false, HttpRedirect.isRedirect(200))
        assertEquals(false, HttpRedirect.isRedirect(304))

        assertEquals(
            "https://cdn.example.com/blob/abc",
            HttpRedirect.resolve("https://huggingface.co/x/resolve/main/m.bin", "https://cdn.example.com/blob/abc"),
        )
        // Relative Location resolved against the current URL.
        assertEquals(
            "https://huggingface.co/x/other.bin",
            HttpRedirect.resolve("https://huggingface.co/x/resolve/main/m.bin", "/x/other.bin"),
        )
    }

    @Test
    fun redirect_refuses_a_downgrade_to_http_or_a_missing_location() {
        assertThrows(IllegalArgumentException::class.java) {
            HttpRedirect.resolve("https://huggingface.co/m.bin", "http://cdn.example.com/m.bin")
        }
        assertThrows(IllegalArgumentException::class.java) {
            HttpRedirect.resolve("https://huggingface.co/m.bin", null)
        }
    }
}
