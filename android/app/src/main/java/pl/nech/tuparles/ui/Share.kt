package pl.nech.tuparles.ui

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import pl.nech.tuparles.data.Note
import java.io.File

private const val AUTHORITY = "pl.nech.tuparles.fileprovider"

/**
 * Share a note's WAV through the system share sheet. The receiving app does any
 * sending — nothing leaves the device unless the user pushes it. No INTERNET here.
 */
fun shareNote(context: Context, note: Note) {
    val file = File(note.wavPath)
    if (!file.exists()) return
    val uri = FileProvider.getUriForFile(context, AUTHORITY, file)
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "audio/wav"
        putExtra(Intent.EXTRA_STREAM, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(intent, "Partager la note").apply {
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    })
}
