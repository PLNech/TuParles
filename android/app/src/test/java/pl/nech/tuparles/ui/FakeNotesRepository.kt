package pl.nech.tuparles.ui

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.data.FtsQuery
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState

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

    override suspend fun update(note: Note) {
        notes.value = notes.value.map { if (it.id == note.id) note else it }
    }

    override suspend fun delete(note: Note) {
        deleted += note
        notes.value = notes.value - note
    }

    override suspend fun get(id: Long): Note? = notes.value.find { it.id == id }

    override suspend fun pendingTranscripts(): List<Note> =
        notes.value.filter { it.transcriptState.inFlight }

    /**
     * A JVM stand-in for FTS4: prefix-token AND match over the transcript, newest-first.
     * Not byte-identical to SQLite FTS, but faithful enough to exercise the ViewModel's
     * search wiring (mode switch, results, untranscribed-hint count).
     */
    override fun search(query: String): Flow<List<Note>> {
        val tokens = FtsQuery.toMatch(query)
            ?.split(" ")
            ?.map { it.removeSuffix("*").lowercase() }
            ?: emptyList()
        return notes.map { list ->
            if (tokens.isEmpty()) {
                emptyList()
            } else {
                list.filter { note ->
                    val words = note.transcript?.lowercase()?.split(Regex("[^\\p{L}\\p{N}]+")).orEmpty()
                    tokens.all { t -> words.any { it.startsWith(t) } }
                }.sortedByDescending { it.createdAt }
            }
        }
    }
}
