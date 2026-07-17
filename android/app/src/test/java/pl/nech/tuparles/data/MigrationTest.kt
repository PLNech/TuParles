package pl.nech.tuparles.data

import androidx.sqlite.db.SupportSQLiteDatabase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.lang.reflect.Proxy

/**
 * Pure-JVM verification of the v1→v2 migration. A real device upgrade (MigrationTestHelper)
 * needs instrumentation and remains device-unverified here, but this drives the actual
 * [MIGRATION_1_2].migrate() through a recording [SupportSQLiteDatabase] proxy and asserts
 * exactly which SQL it emits — catching a wrong column name / type / default at build time.
 */
class MigrationTest {

    @Test
    fun migration_1_2_has_correct_bounds() {
        assertEquals(1, MIGRATION_1_2.startVersion)
        assertEquals(2, MIGRATION_1_2.endVersion)
    }

    @Test
    fun migration_1_2_adds_transcript_state_and_lang_columns() {
        val executed = mutableListOf<String>()
        val db = Proxy.newProxyInstance(
            SupportSQLiteDatabase::class.java.classLoader,
            arrayOf(SupportSQLiteDatabase::class.java),
        ) { _, method, args ->
            if (method.name == "execSQL" && args != null) executed += args[0] as String
            null // migrate() only calls execSQL(String), which returns void
        } as SupportSQLiteDatabase

        MIGRATION_1_2.migrate(db)

        assertEquals(2, executed.size)
        // transcriptState: NOT NULL with a legacy-safe default so existing rows survive.
        assertTrue(
            executed.any {
                it.contains("ADD COLUMN transcriptState") &&
                    it.contains("TEXT") && it.contains("NOT NULL") && it.contains("'NONE'")
            },
        )
        // transcriptLang: nullable provenance column.
        assertTrue(executed.any { it.contains("ADD COLUMN transcriptLang") && it.contains("TEXT") })
        // Additive only — never drops or rewrites existing data (audio is the source of truth).
        assertTrue(executed.none { it.contains("DROP") || it.contains("DELETE") })
    }

    @Test
    fun migration_2_3_has_correct_bounds() {
        assertEquals(2, MIGRATION_2_3.startVersion)
        assertEquals(3, MIGRATION_2_3.endVersion)
    }

    @Test
    fun migration_2_3_creates_fts_index_and_populates_it() {
        val executed = record(MIGRATION_2_3)

        // The external-content FTS4 virtual table over notes.transcript.
        assertTrue(
            executed.any {
                it.contains("CREATE VIRTUAL TABLE") && it.contains("notesFts") &&
                    it.contains("FTS4") && it.contains("content=`notes`")
            },
        )
        // The four content-sync triggers Room expects for an @Fts4(contentEntity=...) table.
        assertTrue(executed.any { it.contains("room_fts_content_sync_notesFts_BEFORE_UPDATE") })
        assertTrue(executed.any { it.contains("room_fts_content_sync_notesFts_BEFORE_DELETE") })
        assertTrue(executed.any { it.contains("room_fts_content_sync_notesFts_AFTER_UPDATE") })
        assertTrue(executed.any { it.contains("room_fts_content_sync_notesFts_AFTER_INSERT") })
        // Populates the index from transcripts already on disk.
        assertTrue(executed.any { it.contains("INSERT INTO `notesFts`(`notesFts`) VALUES('rebuild')") })
    }

    @Test
    fun migration_2_3_never_touches_the_notes_table_or_its_audio() {
        val executed = record(MIGRATION_2_3)
        // Triggers prune the FTS shadow (`notesFts`) only — never the notes rows or WAVs.
        assertTrue(executed.none { it.contains("DROP TABLE") })
        assertTrue(executed.none { it.contains("DELETE FROM `notes`") })
    }

    /** Drives [migration].migrate() through a recording proxy and returns the SQL it emitted. */
    private fun record(migration: androidx.room.migration.Migration): List<String> {
        val executed = mutableListOf<String>()
        val db = Proxy.newProxyInstance(
            SupportSQLiteDatabase::class.java.classLoader,
            arrayOf(SupportSQLiteDatabase::class.java),
        ) { _, method, args ->
            if (method.name == "execSQL" && args != null) executed += args[0] as String
            null
        } as SupportSQLiteDatabase
        migration.migrate(db)
        return executed
    }
}
