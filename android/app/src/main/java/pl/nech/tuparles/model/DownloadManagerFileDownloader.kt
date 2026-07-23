package pl.nech.tuparles.model

import android.app.DownloadManager
import android.content.Context
import androidx.core.net.toUri
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import javax.inject.Inject

/**
 * [FileDownloader] backed by Android's system `DownloadManager`: resumable, survives
 * process death, shows its own progress notification, and needs no extra dependency
 * (no OkHttp/Retrofit — house rule). Bytes stage in app-private external-files; the
 * coordinator ([ModelManager]) verifies the sha256 and moves them into internal storage.
 */
class DownloadManagerFileDownloader @Inject constructor(
    @ApplicationContext private val context: Context,
) : FileDownloader {

    private val dm: DownloadManager
        get() = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager

    override fun enqueue(url: String, title: String, allowMetered: Boolean): Long {
        val fileName = url.substringAfterLast('/')
        val request = DownloadManager.Request(url.toUri())
            .setTitle(title)
            .setDescription("TuParles — modèle de transcription")
            .setAllowedOverMetered(allowMetered)
            .setAllowedOverRoaming(allowMetered)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalFilesDir(context, STAGING_DIR, fileName)
        return dm.enqueue(request)
    }

    override fun status(handle: Long): DownloadStatus {
        dm.query(DownloadManager.Query().setFilterById(handle)).use { c ->
            if (!c.moveToFirst()) return DownloadStatus(RawDownloadState.FAILED, 0L, 0L)
            val status = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
            val soFar = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
            val total = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)).coerceAtLeast(0L)
            val state = when (status) {
                DownloadManager.STATUS_SUCCESSFUL -> RawDownloadState.SUCCESS
                DownloadManager.STATUS_FAILED -> RawDownloadState.FAILED
                DownloadManager.STATUS_PENDING -> RawDownloadState.PENDING
                else -> RawDownloadState.RUNNING // RUNNING or PAUSED — still in flight
            }
            return DownloadStatus(state, soFar.coerceAtLeast(0L), total)
        }
    }

    override fun stagedFile(handle: Long): File? {
        dm.query(DownloadManager.Query().setFilterById(handle)).use { c ->
            if (!c.moveToFirst()) return null
            val status = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
            if (status != DownloadManager.STATUS_SUCCESSFUL) return null
            val localUri = c.getString(c.getColumnIndexOrThrow(DownloadManager.COLUMN_LOCAL_URI))
                ?: return null
            return localUri.toUri().path?.let(::File)
        }
    }

    override fun cancel(handle: Long) {
        dm.remove(handle)
    }

    private companion object {
        const val STAGING_DIR = "models-staging"
    }
}
