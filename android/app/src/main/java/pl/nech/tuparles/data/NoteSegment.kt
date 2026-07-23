package pl.nech.tuparles.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * One committed, silence-bounded segment of a note's rolling transcript (the
 * record-minutes-and-pray fix). Written progressively *during* recording as each segment
 * decodes, so what the speaker sees committed is durable the instant it lands — a process
 * death mid-recording keeps every segment already written here.
 *
 * The rows are the ordered source of truth for a note's transcript: [Note.transcript] is a
 * denormalised concatenation of them (by [segmentIndex]), set once the note is finalised.
 * [startSample]/[endSample] locate each segment on the recording's timeline; being
 * contiguous, they make reconciliation deterministic — no text is duplicated or lost.
 *
 * Segments belong to their note; deleting the note deletes them (the repository prunes
 * them explicitly — no FK, so the migration DDL stays plain). Indexed by [noteId] for the
 * per-note lookup that reconstructs the transcript.
 */
@Entity(
    tableName = "note_segments",
    indices = [Index("noteId")],
)
data class NoteSegment(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val noteId: Long,
    val segmentIndex: Int,
    val text: String,
    val startSample: Long,
    val endSample: Long,
)
