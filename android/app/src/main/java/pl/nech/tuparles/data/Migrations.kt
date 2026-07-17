package pl.nech.tuparles.data

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * v1 → v2: on-device STT columns.
 *
 * Phase A shipped notes with only (id, wavPath, createdAt, durationS, transcript).
 * Phase B adds the transcript lifecycle: [Note.transcriptState] (stored as its enum
 * name, NOT NULL default 'NONE' so existing rows read as never-transcribed) and
 * [Note.transcriptLang] (nullable provenance). Both are additive — no data is
 * touched or dropped, honouring "the audio is the source of truth".
 */
/** The additive statements applied by [MIGRATION_1_2]; exposed so the payload is unit-testable. */
val MIGRATION_1_2_SQL: List<String> = listOf(
    "ALTER TABLE notes ADD COLUMN transcriptState TEXT NOT NULL DEFAULT 'NONE'",
    "ALTER TABLE notes ADD COLUMN transcriptLang TEXT",
)

val MIGRATION_1_2: Migration = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        MIGRATION_1_2_SQL.forEach(db::execSQL)
    }
}
