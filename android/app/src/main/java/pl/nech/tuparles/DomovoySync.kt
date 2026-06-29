package pl.nech.tuparles

import android.content.Context
import org.json.JSONObject
import pl.nech.domovoy.analytics.DomovoyAnalyticsEvent
import pl.nech.domovoy.analytics.DomovoyAnalyticsSink
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Durable, local-first telemetry transport — built for "away for 7 days, recover
 * on return". The Sink APPENDS every event to an append-only outbox file that
 * survives the whole trip: unlike the analytics lib's bounded in-memory queue, this
 * file is never trimmed on capture, so nothing is dropped while domovoy is out of
 * reach. A best-effort drain POSTs the outbox to domovoy WHEN reachable (home LAN
 * now, or the moment you're back on home WiFi); it rotates the outbox aside first so
 * events logged mid-send are not lost, and only deletes a batch on a confirmed 2xx.
 *
 * With no INTERNET permission (the release flavor) the POST throws and is swallowed,
 * so capture keeps working and the outbox simply waits for an `adb pull`. Nothing
 * here ever blocks or crashes a take.
 */
object DomovoySync {
    private const val TAG = "TuParles"
    private const val APP = "tuparles"

    // domovoy ingest endpoint. LAN host for now; the durable outbox is what covers
    // being away — this URL only needs to resolve when a drain actually fires.
    // TODO(A4): confirm port/path/auth against the domovoy collector before relying
    // on live sync; capture + adb-pull works regardless of this value.
    private const val DOMOVOY_URL = "http://domovoy.local:8087/api/observations"

    private fun outbox(c: Context): File? =
        c.getExternalFilesDir("telemetry")?.let { File(it, "outbox.jsonl") }

    /** The lib hands us batches; we durably append and report accepted. */
    fun sink(context: Context): DomovoyAnalyticsSink {
        val app = context.applicationContext
        return DomovoyAnalyticsSink { events ->
            // Private mode: drop on the floor (report accepted so the lib clears its
            // in-memory queue too) — nothing reaches disk or domovoy until you're back.
            if (Settings.privateMode(app)) return@DomovoyAnalyticsSink true
            append(app, events)
            true // accepted into our durable outbox; network drain is separate
        }
    }

    @Synchronized
    private fun append(c: Context, events: List<DomovoyAnalyticsEvent>) {
        val f = outbox(c) ?: return
        f.parentFile?.mkdirs()
        try {
            f.appendText(buildString { for (e in events) append(toJson(e).toString()).append('\n') })
        } catch (t: Throwable) {
            DebugLog.w(TAG, "telemetry: append failed (${t.javaClass.simpleName})")
        }
    }

    internal fun toJson(e: DomovoyAnalyticsEvent): JSONObject = JSONObject().apply {
        put("app", APP)
        put("observed_at_ms", e.observedAtMillis)
        put("name", e.name)
        put("category", e.category)
        put("severity", e.severity)
        put("session_id", e.sessionId)
        put("run_id", e.runId)
        put("attributes", JSONObject().also { a ->
            for ((k, v) in e.attributes) when (v) {
                null -> {}
                is Float -> a.put(k, v.toDouble()) // JSON has no float
                is Int, is Long, is Double, is Boolean, is String -> a.put(k, v)
                else -> a.put(k, v.toString())
            }
        })
    }

    /**
     * Best-effort drain. Rotates outbox.jsonl → outbox.sending.jsonl (so concurrent
     * appends land in a fresh outbox), POSTs the batch, deletes it on 2xx, or merges
     * it back on failure. Safe to call repeatedly; a no-op when empty or unreachable.
     */
    @Synchronized
    fun drain(c: Context): Boolean {
        val f = outbox(c) ?: return false
        val sending = File(f.parentFile, "outbox.sending.jsonl")
        // Carry over any leftover from a previously-failed send, then take the current.
        try {
            if (f.exists() && f.length() > 0L) {
                if (sending.exists()) sending.appendText(f.readText()) else f.renameTo(sending)
                if (f.exists()) f.delete()
            }
        } catch (_: Throwable) {
            return false
        }
        if (!sending.exists() || sending.length() == 0L) return true

        val body = try { sending.readText() } catch (_: Throwable) { return false }
        return try {
            val conn = (URL(DOMOVOY_URL).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 6000
                doOutput = true
                setRequestProperty("Content-Type", "application/x-ndjson")
            }
            conn.outputStream.use { it.write(body.toByteArray()) }
            val ok = conn.responseCode in 200..299
            conn.disconnect()
            if (ok) {
                sending.delete()
                DebugLog.i(TAG, "telemetry: drained ${body.count { it == '\n' }} events to domovoy")
            } else {
                DebugLog.w(TAG, "telemetry: domovoy HTTP ${conn.responseCode}; outbox kept")
            }
            ok
        } catch (e: Throwable) {
            // No INTERNET (release flavor) or domovoy unreachable (away): keep the batch.
            DebugLog.d(TAG, "telemetry: drain skipped (${e.javaClass.simpleName}); outbox kept")
            false
        }
    }
}
