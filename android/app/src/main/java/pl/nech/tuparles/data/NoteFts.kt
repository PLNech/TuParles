package pl.nech.tuparles.data

import androidx.room.Entity
import androidx.room.Fts4

/**
 * External-content FTS4 index over [Note.transcript] (issue #40, Phase C).
 *
 * `contentEntity = Note::class` means this virtual table stores no data of its own —
 * it indexes the `notes` table, and Room generates the sync triggers that keep the
 * index in step with every insert/update/delete on a note. We never write to it
 * directly; search joins back to `notes` via `docid` (= `notes.rowid` = [Note.id]).
 *
 * FTS4 (not FTS5) is the design-doc choice and the one Room annotates natively; a
 * blank/absent transcript simply produces no index term, so un-transcribed notes are
 * naturally absent from text-search results without any extra filtering.
 */
@Fts4(contentEntity = Note::class)
@Entity(tableName = "notesFts")
data class NoteFts(
    val transcript: String?,
)
