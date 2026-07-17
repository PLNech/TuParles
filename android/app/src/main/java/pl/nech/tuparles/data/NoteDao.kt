package pl.nech.tuparles.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface NoteDao {
    @Query("SELECT * FROM notes ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<Note>>

    @Query("SELECT * FROM notes WHERE id = :id")
    suspend fun get(id: Long): Note?

    @Query("SELECT * FROM notes WHERE transcriptState IN ('PENDING', 'RUNNING') ORDER BY createdAt ASC")
    suspend fun pendingTranscripts(): List<Note>

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
