package pl.nech.tuparles.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One recorded note. The WAV is always present (a dictaphone keeps the audio);
 * [transcript] is null until on-device STT decodes it (or it's re-decoded on the
 * desktop). [durationS] and [createdAt] drive the list without touching the file.
 *
 * [transcriptState] tracks the decode lifecycle (see [TranscriptState]); [transcriptLang]
 * records which language the engine reported, for provenance. Both are added in the
 * v1→v2 migration (see data/Migrations.kt) — legacy rows default to NONE / null.
 */
@Entity(tableName = "notes")
data class Note(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val wavPath: String,
    val createdAt: Long,
    val durationS: Float,
    val transcript: String? = null,
    val transcriptState: TranscriptState = TranscriptState.NONE,
    val transcriptLang: String? = null,
)
