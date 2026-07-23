package pl.nech.tuparles.model

import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest

/** In-memory [ModelPreferences] for JVM tests. */
class FakeModelPreferences(
    override var activeModelId: String? = null,
    override var firstRunCardDismissed: Boolean = false,
) : ModelPreferences

/** Records [PendingWork.retryPending] calls so tests can assert the auto-transcribe trigger. */
class RecordingPendingWork : PendingWork {
    var retries = 0
    override fun retryPending() {
        retries++
    }
}

/**
 * Scriptable [FileDownloader]: hands back a fixed sequence of [DownloadStatus] (the last
 * repeats), and a caller-provided staged file on success. No Android, no network.
 */
class FakeFileDownloader(
    private val script: List<DownloadStatus>,
    private val staged: () -> File?,
) : FileDownloader {
    var enqueued = 0
    var cancelled = 0
    private var polls = 0

    override fun enqueue(url: String, title: String, allowMetered: Boolean): Long {
        enqueued++
        return 42L
    }

    override fun status(handle: Long): DownloadStatus =
        script[minOf(polls++, script.lastIndex)]

    override fun stagedFile(handle: Long): File? = staged()

    override fun cancel(handle: Long) {
        cancelled++
    }
}

/** Real lower-case hex sha256 of [bytes] (mirrors [ModelStore.sha256] for building test specs). */
fun sha256Of(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

/**
 * Create a sparse file of exactly [size] bytes on disk (no real blocks allocated) so
 * [ModelStore.isInstalled] — which only checks the length — reports a catalog model as
 * installed without needing a real multi-hundred-MB download in a unit test.
 */
fun sparseFile(file: File, size: Long): File {
    file.parentFile?.mkdirs()
    RandomAccessFile(file, "rw").use { it.setLength(size) }
    return file
}
