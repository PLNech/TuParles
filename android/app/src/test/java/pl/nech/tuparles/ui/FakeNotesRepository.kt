package pl.nech.tuparles.ui

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.data.Note

/** In-memory NotesRepository for unit tests — no Room, no Android. */
class FakeNotesRepository : NotesRepository {
    private val notes = MutableStateFlow<List<Note>>(emptyList())
    val deleted = mutableListOf<Note>()

    fun emit(list: List<Note>) {
        notes.value = list
    }

    override fun observeNotes(): Flow<List<Note>> = notes

    override suspend fun add(note: Note): Long {
        notes.value = notes.value + note
        return note.id
    }

    override suspend fun delete(note: Note) {
        deleted += note
        notes.value = notes.value - note
    }

    override suspend fun get(id: Long): Note? = notes.value.find { it.id == id }
}
