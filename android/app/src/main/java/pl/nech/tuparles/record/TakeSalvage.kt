package pl.nech.tuparles.record

import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import java.io.File

/**
 * What to do with a take the service did not get to finish: a system screen
 * covered the app, the process is dying, or stop raced the insert. The list
 * hides `RECORDING`, so the row must leave that state or be deleted. Never
 * both hidden and gone.
 *
 * Returns the path name for the log line. The caller logs it with the note id,
 * duration, and pcm length — never the transcript text.
 */
suspend fun salvageInterruptedTake(
    notes: NotesRepository,
    noteId: Long,
    wav: File?,
    pcmSamples: Int,
    onPending: (Long) -> Unit = {},
): String {
    val onDisk = wav?.let { wavSampleCount(it) } ?: 0
    val samples = maxOf(pcmSamples, onDisk)
    val note = if (noteId != 0L) notes.get(noteId) else null
    if (note != null && note.transcriptState != TranscriptState.RECORDING) return "saved"

    val segments = if (note != null) notes.segmentsFor(note.id) else emptyList()
    val committed = segments.joinToString(" ") { it.text }.trim()
    val durationS = samples.toFloat() / SAMPLE_RATE

    if (samples <= 0 && committed.isEmpty()) {
        note?.let { notes.delete(it) }
        wav?.delete()
        return "dropped-empty"
    }

    val id = note?.id ?: notes.add(
        Note(
            wavPath = wav?.absolutePath ?: "",
            createdAt = System.currentTimeMillis(),
            durationS = durationS,
            transcriptState = TranscriptState.RECORDING,
        ),
    )
    val current = notes.get(id) ?: return "dropped-empty"
    val wavOk = wav != null && wav.exists() && onDisk > 0
    val updated = when {
        // Committed text is kept as-is. A later whole-file decode would rewrite it.
        committed.isNotEmpty() -> current.copy(
            transcript = committed,
            transcriptState = TranscriptState.DONE,
            durationS = durationS,
        )
        // Audio reached disk and nothing is committed yet: the post-hoc decode can run.
        wavOk -> current.copy(
            transcriptState = TranscriptState.PENDING,
            durationS = durationS,
        )
        // Samples existed only in RAM. Visible failure, never a silent absence.
        else -> current.copy(
            transcriptState = TranscriptState.FAILED,
            durationS = durationS,
        )
    }
    notes.update(updated)
    if (updated.transcriptState == TranscriptState.PENDING) onPending(id)
    return "destroyed-while-recording"
}
