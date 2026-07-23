package pl.nech.tuparles.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface NoteDao {
    // A note being recorded (its rolling transcript still growing) is hidden from the list
    // until it finalises; every finished/legacy note shows as before.
    @Query("SELECT * FROM notes WHERE transcriptState != 'RECORDING' ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<Note>>

    @Query("SELECT * FROM notes WHERE id = :id")
    suspend fun get(id: Long): Note?

    @Query("SELECT * FROM notes WHERE transcriptState IN ('PENDING', 'RUNNING') ORDER BY createdAt ASC")
    suspend fun pendingTranscripts(): List<Note>

    /** Notes left mid-recording by a process death — recovered from their committed segments. */
    @Query("SELECT * FROM notes WHERE transcriptState = 'RECORDING' ORDER BY createdAt ASC")
    suspend fun recordingNotes(): List<Note>

    @Insert
    suspend fun insertSegment(segment: NoteSegment): Long

    @Query("SELECT * FROM note_segments WHERE noteId = :noteId ORDER BY segmentIndex ASC")
    suspend fun segmentsFor(noteId: Long): List<NoteSegment>

    @Query("DELETE FROM note_segments WHERE noteId = :noteId")
    suspend fun deleteSegmentsFor(noteId: Long)

    /**
     * Full-text search over transcripts (issue #40). [match] is an FTS4 MATCH
     * expression built by [FtsQuery.toMatch]; the join pins each hit back to its
     * note by docid. Ranked by recency — newest first — which is fine for a
     * personal dictaphone (no scoring gymnastics).
     */
    @Query(
        "SELECT notes.* FROM notes JOIN notesFts ON notes.id = notesFts.docid " +
            "WHERE notesFts MATCH :match ORDER BY notes.createdAt DESC",
    )
    fun search(match: String): Flow<List<Note>>

    @Insert
    suspend fun insert(note: Note): Long

    @Update
    suspend fun update(note: Note)

    @Delete
    suspend fun delete(note: Note)
}
