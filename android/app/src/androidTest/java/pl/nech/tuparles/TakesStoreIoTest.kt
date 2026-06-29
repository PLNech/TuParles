package pl.nech.tuparles

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * The history store's file IO + the vote/correct rewrite + the profiling aggregation,
 * tested against a TEMP file in cacheDir — never the user's real takes.jsonl (the IO
 * was refactored to File-parameterized internals precisely so this is safe). Pins the
 * append→read order, the in-place update rewrite, and the stats math the Historique
 * screen renders.
 */
@RunWith(AndroidJUnit4::class)
class TakesStoreIoTest {

    private lateinit var f: File

    private fun rec(id: Long, model: String = "m", rtf: Float = 1f, ms: Long = 100L,
                    vote: Int = 0, corrected: String? = null, error: String? = null) =
        TakeRecord(id = id, ts = id, model = model, lang = "fr", audioS = 1f, decodeMs = ms,
            rtf = rtf, chars = 3, raw = "raw$id", clean = "clean$id",
            corrected = corrected, vote = vote, target = "scratch", error = error)

    @Before fun setUp() {
        val dir = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
        f = File(dir, "takes_test_${System.nanoTime()}.jsonl")
        f.delete()
    }

    @After fun tearDown() { f.delete() }

    @Test fun empty_reads_empty() {
        assertEquals(emptyList<TakeRecord>(), TakesStore.allFrom(f))
        assertEquals(0, TakesStore.statsOf(emptyList()).n)
    }

    @Test fun append_then_read_preserves_order_and_fields() {
        TakesStore.appendTo(f, rec(1))
        TakesStore.appendTo(f, rec(2))
        val rows = TakesStore.allFrom(f)
        assertEquals(listOf(1L, 2L), rows.map { it.id })
        assertEquals("clean1", rows[0].clean)
    }

    @Test fun update_sets_vote_and_correction_in_place() {
        TakesStore.appendTo(f, rec(1))
        TakesStore.appendTo(f, rec(2))
        TakesStore.updateIn(f, id = 2, vote = -1, corrected = "fixed")
        val rows = TakesStore.allFrom(f).associateBy { it.id }
        assertEquals(0, rows.getValue(1).vote)          // untouched
        assertEquals(-1, rows.getValue(2).vote)
        assertEquals("fixed", rows.getValue(2).corrected)
        assertEquals(2, TakesStore.allFrom(f).size)     // rewrite didn't drop/dup rows
    }

    @Test fun update_partial_keeps_other_field() {
        TakesStore.appendTo(f, rec(1, vote = 1, corrected = "keep"))
        TakesStore.updateIn(f, id = 1, vote = -1) // corrected stays
        val r = TakesStore.allFrom(f).first()
        assertEquals(-1, r.vote)
        assertEquals("keep", r.corrected)
    }

    @Test fun stats_aggregate_is_correct() {
        TakesStore.appendTo(f, rec(1, model = "base", rtf = 1.0f, ms = 100, vote = 1))
        TakesStore.appendTo(f, rec(2, model = "base", rtf = 2.0f, ms = 300, vote = -1, corrected = "x"))
        TakesStore.appendTo(f, rec(3, model = "med", error = "boom"))
        val s = TakesStore.statsOf(TakesStore.allFrom(f))
        assertEquals(3, s.n)
        assertEquals(1, s.errors)
        assertEquals(1, s.upvotes)
        assertEquals(1, s.downvotes)
        assertEquals(1, s.corrected)
        // means over the OK rows only (errors excluded): rtf (1+2)/2=1.5, ms (100+300)/2=200
        assertEquals(1.5f, s.meanRtf, 1e-4f)
        assertEquals(200L, s.meanMs)
        assertEquals(mapOf("base" to 2, "med" to 1), s.perModel)
    }

    @Test fun corrupt_lines_skipped_not_fatal() {
        TakesStore.appendTo(f, rec(1))
        f.appendText("garbage not json\n")
        TakesStore.appendTo(f, rec(2))
        assertTrue(TakesStore.allFrom(f).map { it.id }.containsAll(listOf(1L, 2L)))
        assertEquals(2, TakesStore.allFrom(f).size) // the garbage line is dropped, not counted
    }
}
