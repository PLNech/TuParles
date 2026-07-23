package pl.nech.tuparles.model

import android.content.Context
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject

/**
 * The in-app fallback [FileDownloader]: a plain `HttpURLConnection` streaming straight to
 * the app-private staging area, used only when the system `DownloadManager` stalls (see
 * [StallDetector] and the Android-15 forensics in the design note). No extra dependency
 * (no OkHttp/Retrofit — house rule); redirect resolution and the byte-pump are the pure,
 * unit-tested [HttpRedirect] and [HttpStreamCopier].
 *
 * Honest tradeoff (documented in the design note too): this path lives **in the app
 * process** — it does not survive process death and cannot resume a partial. That is
 * acceptable for a *fallback*: `DownloadManager` stays primary precisely for its
 * background-survival; we reach for this only when the scheduler never starts the job,
 * where an in-process transfer that actually moves bytes beats one that never does.
 * The finished file is handed to the same verify + atomic-install path unchanged.
 */
class DirectHttpFileDownloader @Inject constructor(
    @ApplicationContext private val context: Context,
) : FileDownloader {

    // The pure byte-pump (unit-tested on its own). Not injected — it carries only tuning
    // constants, no dependencies.
    private val copier = HttpStreamCopier()
    private val io = Executors.newCachedThreadPool { r -> Thread(r, "tuparles-direct-dl").apply { isDaemon = true } }
    private val downloads = ConcurrentHashMap<Long, Transfer>()
    private val nextHandle = AtomicLong(1L)

    override fun enqueue(url: String, title: String, allowMetered: Boolean): Long {
        val handle = nextHandle.getAndIncrement()
        val fileName = url.substringAfterLast('/')
        val dir = File(context.getExternalFilesDir(null), STAGING_DIR).apply { mkdirs() }
        val dest = File(dir, "direct-$fileName")
        val transfer = Transfer(dest)
        downloads[handle] = transfer
        io.execute { transfer.run(url, copier) }
        return handle
    }

    override fun status(handle: Long): DownloadStatus =
        downloads[handle]?.snapshot() ?: DownloadStatus(RawDownloadState.FAILED, 0L, 0L)

    override fun stagedFile(handle: Long): File? =
        downloads[handle]?.let { if (it.state == RawDownloadState.SUCCESS) it.dest else null }

    override fun cancel(handle: Long) {
        downloads.remove(handle)?.cancel()
    }

    /** One in-flight transfer, its progress readable from any thread via volatiles. */
    private class Transfer(val dest: File) {
        @Volatile var state: RawDownloadState = RawDownloadState.PENDING
        @Volatile var bytesSoFar: Long = 0L
        @Volatile var totalBytes: Long = 0L
        @Volatile private var cancelled = false

        fun snapshot() = DownloadStatus(state, bytesSoFar, totalBytes)

        fun cancel() {
            cancelled = true
            runCatching { dest.delete() }
        }

        fun run(startUrl: String, copier: HttpStreamCopier) {
            var conn: HttpURLConnection? = null
            try {
                var url = startUrl
                var hops = 0
                while (true) {
                    conn = (URL(url).openConnection() as HttpURLConnection).apply {
                        instanceFollowRedirects = false // we resolve redirects ourselves (https-only)
                        connectTimeout = CONNECT_TIMEOUT_MS
                        readTimeout = READ_TIMEOUT_MS
                        requestMethod = "GET"
                    }
                    val code = conn.responseCode
                    if (HttpRedirect.isRedirect(code)) {
                        if (++hops > HttpRedirect.MAX_REDIRECTS) throw java.io.IOException("too many redirects")
                        url = HttpRedirect.resolve(url, conn.getHeaderField("Location"))
                        conn.disconnect()
                        continue
                    }
                    if (code != HttpURLConnection.HTTP_OK) throw java.io.IOException("HTTP $code")
                    break
                }
                state = RawDownloadState.RUNNING
                totalBytes = conn!!.contentLengthLong.coerceAtLeast(0L)
                conn.inputStream.use { input ->
                    copier.copy(
                        input = input,
                        dest = dest,
                        isCancelled = { cancelled },
                        onProgress = { bytesSoFar = it },
                    )
                }
                state = if (cancelled) RawDownloadState.FAILED else RawDownloadState.SUCCESS
            } catch (t: Throwable) {
                if (!cancelled) Log.w("TuParles", "direct download failed for $startUrl", t)
                runCatching { dest.delete() }
                state = RawDownloadState.FAILED
            } finally {
                runCatching { conn?.disconnect() }
            }
        }
    }

    private companion object {
        const val STAGING_DIR = "models-staging"
        const val CONNECT_TIMEOUT_MS = 30_000
        const val READ_TIMEOUT_MS = 60_000
    }
}
