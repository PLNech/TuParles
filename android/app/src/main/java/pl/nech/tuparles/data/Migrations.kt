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

/**
 * v2 → v3: transcript full-text search (issue #40, Phase C).
 *
 * Adds the external-content FTS4 index [NoteFts] over `notes.transcript`, plus the four
 * content-sync triggers Room expects for an `@Fts4(contentEntity = …)` table (Room only
 * emits these itself on a fresh create, so a migration must replicate them verbatim — the
 * DDL matches Room's generated `createAllTables` so open-time schema validation passes).
 * The final `rebuild` command populates the index from the transcripts already on disk.
 *
 * Purely additive to user data: the `notes` table is untouched (the DELETEs below live
 * inside the sync triggers and only ever prune the FTS shadow index, never a note or its
 * audio — the WAV stays the source of truth).
 */
val MIGRATION_2_3_SQL: List<String> = listOf(
    "CREATE VIRTUAL TABLE IF NOT EXISTS `notesFts` USING FTS4(`transcript` TEXT, content=`notes`)",
    "CREATE TRIGGER IF NOT EXISTS room_fts_content_sync_notesFts_BEFORE_UPDATE BEFORE UPDATE ON `notes` " +
        "BEGIN DELETE FROM `notesFts` WHERE `docid`=OLD.`rowid`; END",
    "CREATE TRIGGER IF NOT EXISTS room_fts_content_sync_notesFts_BEFORE_DELETE BEFORE DELETE ON `notes` " +
        "BEGIN DELETE FROM `notesFts` WHERE `docid`=OLD.`rowid`; END",
    "CREATE TRIGGER IF NOT EXISTS room_fts_content_sync_notesFts_AFTER_UPDATE AFTER UPDATE ON `notes` " +
        "BEGIN INSERT INTO `notesFts`(`docid`, `transcript`) VALUES (NEW.`rowid`, NEW.`transcript`); END",
    "CREATE TRIGGER IF NOT EXISTS room_fts_content_sync_notesFts_AFTER_INSERT AFTER INSERT ON `notes` " +
        "BEGIN INSERT INTO `notesFts`(`docid`, `transcript`) VALUES (NEW.`rowid`, NEW.`transcript`); END",
    "INSERT INTO `notesFts`(`notesFts`) VALUES('rebuild')",
)

val MIGRATION_2_3: Migration = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        MIGRATION_2_3_SQL.forEach(db::execSQL)
    }
}
