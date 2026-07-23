package pl.nech.tuparles.model

import java.io.File

/**
 * The minimal slice of Android's `DownloadManager` the model subsystem depends on,
 * abstracted behind an interface so the download *coordination* (progress, verify,
 * atomic install, retry-pending) is pure Kotlin and unit-testable on the JVM with a
 * fake. The real implementation ([pl.nech.tuparles.model.DownloadManagerFileDownloader])
 * delegates to the system service — resumable, survives process death, no extra deps.
 */
interface FileDownloader {

    /**
     * Begin fetching [url] into a private staging location. Returns an opaque handle.
     * @param allowMetered whether the user has agreed to spend cellular data (they are
     *   shown the size first — no silent large downloads).
     */
    fun enqueue(url: String, title: String, allowMetered: Boolean): Long

    /** Current status of the download identified by [handle]. */
    fun status(handle: Long): DownloadStatus

    /**
     * The finished, staged file for [handle], or null if not finished / unavailable.
     * The coordinator verifies and moves this into place; the staging copy is disposable.
     */
    fun stagedFile(handle: Long): File?

    /** Cancel and remove the download and any partial bytes. */
    fun cancel(handle: Long)
}

/** A poll snapshot from the underlying downloader. */
data class DownloadStatus(
    val state: RawDownloadState,
    val bytesSoFar: Long,
    val totalBytes: Long,
)

enum class RawDownloadState { PENDING, RUNNING, SUCCESS, FAILED }
