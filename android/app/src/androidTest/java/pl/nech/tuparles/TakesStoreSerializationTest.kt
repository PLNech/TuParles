package pl.nech.tuparles

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The learning store's backbone is the JSONL codec: every take, vote, and correction
 * survives a round-trip through it or the trip's labels are silently lost. This pins
 * toJson→fromJson on the device's real org.json (no file IO, so it never touches the
 * user's actual takes.jsonl). Instrumentation, not pure-JVM, because org.json is only
 * a throwing stub off-device.
 */
@RunWith(AndroidJUnit4::class)
class TakesStoreSerializationTest {

    @Test fun roundTrip_full_record() {
        val rec = TakeRecord(
            id = 42L, ts = 1_700_000_000_000L, model = "ggml-base.bin", lang = "fr",
            audioS = 1.2f, decodeMs = 1530L, rtf = 1.27f, chars = 18,
            raw = "alors j'ai fait un quick refactor", clean = "Alors j'ai fait un quick refactor.",
            corrected = "Alors j'ai fait un quick refactor du pipeline.", vote = 1,
            target = "ime", error = null,
        )
        val back = TakesStore.fromJson(TakesStore.toJson(rec).toString())!!
        assertEquals(rec.id, back.id)
        assertEquals(rec.ts, back.ts)
        assertEquals(rec.model, back.model)
        assertEquals(rec.lang, back.lang)
        assertEquals(rec.audioS, back.audioS, 1e-4f)
        assertEquals(rec.decodeMs, back.decodeMs)
        assertEquals(rec.rtf, back.rtf, 1e-4f)
        assertEquals(rec.chars, back.chars)
        assertEquals(rec.raw, back.raw)
        assertEquals(rec.clean, back.clean)
        assertEquals(rec.corrected, back.corrected)
        assertEquals(rec.vote, back.vote)
        assertEquals(rec.target, back.target)
        assertNull(back.error)
    }

    @Test fun roundTrip_minimal_omits_optionals() {
        val rec = TakeRecord(
            id = 1L, ts = 1L, model = "m", lang = "auto",
            audioS = 0f, decodeMs = 0L, rtf = 0f, chars = 0,
            raw = "", clean = "", target = "scratch",
        )
        val json = TakesStore.toJson(rec)
        // optionals must NOT be written when absent (keeps the JSONL honest + compact)
        assertEquals(false, json.has("corrected"))
        assertEquals(false, json.has("error"))
        val back = TakesStore.fromJson(json.toString())!!
        assertNull(back.corrected)
        assertNull(back.error)
        assertEquals(0, back.vote)
    }

    @Test fun roundTrip_error_record() {
        val rec = TakeRecord(
            id = 7L, ts = 2L, model = "m", lang = "en",
            audioS = 0.5f, decodeMs = 90000L, rtf = 0f, chars = 0,
            raw = "", clean = "", target = "widget", error = "decode timeout",
        )
        val back = TakesStore.fromJson(TakesStore.toJson(rec).toString())!!
        assertEquals("decode timeout", back.error)
    }

    @Test fun fromJson_garbage_is_null_not_crash() {
        assertNull(TakesStore.fromJson("not json at all {{{"))
    }
}
