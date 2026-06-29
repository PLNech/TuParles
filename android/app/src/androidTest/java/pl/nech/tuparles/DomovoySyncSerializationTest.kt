package pl.nech.tuparles

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import pl.nech.domovoy.analytics.DomovoyAnalyticsEvent

/**
 * The typed-telemetry contract (G): an event's attributes must reach the outbox JSON
 * as NATIVE types — int as int, float as double (JSON has no float), bool as bool —
 * or domovoy's duckdb/NLP layer charts strings instead of numbers. This pins
 * DomovoySync.toJson on the device's real org.json. No IO, no network.
 */
@RunWith(AndroidJUnit4::class)
class DomovoySyncSerializationTest {

    private fun event(attrs: Map<String, Any?>) = DomovoyAnalyticsEvent(
        observedAtMillis = 1_700_000_000_000L, name = "take", category = "performance",
        severity = "info", sessionId = "s1", runId = "r1", attributes = attrs,
    )

    @Test fun primitives_keep_native_json_types() {
        val json = DomovoySync.toJson(event(mapOf(
            "audio_s" to 1.2f, "decode_ms" to 1530L, "rtf" to 1.27, "chars" to 18,
            "ok" to true, "model" to "ggml-base.bin",
        )))
        val a = json.getJSONObject("attributes")
        // numbers as numbers (the whole point — duckdb must aggregate, not parse strings)
        assertEquals(1530, a.getLong("decode_ms"))
        assertEquals(18, a.getInt("chars"))
        assertEquals(1.27, a.getDouble("rtf"), 1e-9)
        assertEquals(1.2, a.getDouble("audio_s"), 1e-4) // Float widened to Double
        assertTrue(a.getBoolean("ok"))
        assertEquals("ggml-base.bin", a.getString("model"))
        // the type, not just the value: a JSON number must not be a quoted string
        assertTrue("decode_ms must be a Number", a.get("decode_ms") is Number)
        assertTrue("ok must be a Boolean", a.get("ok") is Boolean)
    }

    @Test fun nulls_are_skipped() {
        val json = DomovoySync.toJson(event(mapOf("present" to 1, "absent" to null)))
        val a = json.getJSONObject("attributes")
        assertTrue(a.has("present"))
        assertFalse("null attributes must be omitted, not JSON null", a.has("absent"))
    }

    @Test fun envelope_fields_present() {
        val json = DomovoySync.toJson(event(emptyMap()))
        assertEquals("tuparles", json.getString("app"))
        assertEquals("take", json.getString("name"))
        assertEquals("performance", json.getString("category"))
        assertEquals(1_700_000_000_000L, json.getLong("observed_at_ms"))
        assertEquals("s1", json.getString("session_id"))
    }
}
