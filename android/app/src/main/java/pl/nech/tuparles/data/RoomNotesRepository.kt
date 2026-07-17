package pl.nech.tuparles.data

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import pl.nech.tuparles.core.NotesRepository
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class RoomNotesRepository @Inject constructor(
    private val dao: NoteDao,
) : NotesRepository {
    override fun observeNotes(): Flow<List<Note>> = dao.observeAll()
    override suspend fun add(note: Note): Long = dao.insert(note)
    override suspend fun update(note: Note) = dao.update(note)
    override suspend fun delete(note: Note) = dao.delete(note)
    override suspend fun get(id: Long): Note? = dao.get(id)
    override suspend fun pendingTranscripts(): List<Note> = dao.pendingTranscripts()

    // Blank/punctuation-only input has nothing to match — return an empty result
    // rather than a malformed FTS query (the ViewModel shows the full list for those).
    override fun search(query: String): Flow<List<Note>> =
        FtsQuery.toMatch(query)?.let(dao::search) ?: flowOf(emptyList())
}
