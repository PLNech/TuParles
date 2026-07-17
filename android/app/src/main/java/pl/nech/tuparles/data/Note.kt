package pl.nech.tuparles.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One recorded note. The WAV is always present (a dictaphone keeps the audio);
 * [transcript] is null until Phase B decodes it on-device (or it's re-decoded on
 * the desktop). [durationS] and [createdAt] drive the list without touching the file.
 */
@Entity(tableName = "notes")
data class Note(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val wavPath: String,
    val createdAt: Long,
    val durationS: Float,
    val transcript: String? = null,
)
