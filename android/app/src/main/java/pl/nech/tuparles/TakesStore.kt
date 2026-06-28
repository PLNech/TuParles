package pl.nech.tuparles

import android.content.Context
import org.json.JSONObject
import java.io.File

/**
 * One dictation, durably recorded: the raw decode, the cleaned text, optionally the
 * user's correction + a vote, plus the profiling metrics (audio length, decode time,
 * RTF). This single record IS the history row, the profiling sample, AND the learning
 * label ({raw, clean, corrected} teaches the lexicon / a future fine-tune).
 */
data class TakeRecord(
    val id: Long,
    val ts: Long,
    val model: String,
    val lang: String,
    val audioS: Float,
    val decodeMs: Long,
    val rtf: Float,
    val chars: Int,
    val raw: String,
    val clean: String,
    val corrected: String? = null,
    val vote: Int = 0, // -1 down, 0 none, +1 up
    val target: String = "",
    val error: String? = null,
)

/**
 * Append-only local history of takes (getExternalFilesDir("history")/takes.jsonl).
 * Durable across the trip; reviewable on return; the source for the in-app profiling
 * stats and the learning export. Suppressed entirely in private mode (the caller
 * checks). Edits (vote/correct) rewrite the file — fine at human dictation scale.
 */
object TakesStore {
    private const val TAG = "TuParles"

    private fun file(c: Context): File? =
        c.getExternalFilesDir("history")?.let { File(it, "takes.jsonl") }

    @Synchronized
    fun append(c: Context, rec: TakeRecord) {
        val f = file(c) ?: return
        f.parentFile?.mkdirs()
        try {
            f.appendText(toJson(rec).toString() + "\n")
        } catch (t: Throwable) {
            DebugLog.w(TAG, "takes: append failed (${t.javaClass.simpleName})")
        }
    }

    @Synchronized
    fun all(c: Context): List<TakeRecord> {
        val f = file(c) ?: return emptyList()
        if (!f.exists()) return emptyList()
        return try {
            f.readLines().filter { it.isNotBlank() }.mapNotNull { fromJson(it) }
        } catch (_: Throwable) {
            emptyList()
        }
    }

    @Synchronized
    fun update(c: Context, id: Long, vote: Int? = null, corrected: String? = null) {
        val f = file(c) ?: return
        val rows = all(c).map {
            if (it.id == id) it.copy(
                vote = vote ?: it.vote,
                corrected = corrected ?: it.corrected,
            ) else it
        }
        try {
            f.writeText(rows.joinToString("\n") { toJson(it).toString() } + "\n")
        } catch (t: Throwable) {
            DebugLog.w(TAG, "takes: update failed (${t.javaClass.simpleName})")
        }
    }

    /** Aggregate profiling — the answer to "where's the profiling?". */
    data class Stats(
        val n: Int,
        val errors: Int,
        val meanRtf: Float,
        val meanMs: Long,
        val upvotes: Int,
        val downvotes: Int,
        val corrected: Int,
        val perModel: Map<String, Int>,
    )

    fun stats(c: Context): Stats {
        val rows = all(c)
        if (rows.isEmpty()) return Stats(0, 0, 0f, 0L, 0, 0, 0, emptyMap())
        val ok = rows.filter { it.error == null }
        return Stats(
            n = rows.size,
            errors = rows.count { it.error != null },
            meanRtf = if (ok.isEmpty()) 0f else ok.map { it.rtf }.average().toFloat(),
            meanMs = if (ok.isEmpty()) 0L else ok.map { it.decodeMs }.average().toLong(),
            upvotes = rows.count { it.vote > 0 },
            downvotes = rows.count { it.vote < 0 },
            corrected = rows.count { !it.corrected.isNullOrBlank() },
            perModel = rows.groupingBy { it.model }.eachCount(),
        )
    }

    private fun toJson(r: TakeRecord) = JSONObject().apply {
        put("id", r.id); put("ts", r.ts); put("model", r.model); put("lang", r.lang)
        put("audio_s", r.audioS.toDouble()); put("decode_ms", r.decodeMs)
        put("rtf", r.rtf.toDouble()); put("chars", r.chars)
        put("raw", r.raw); put("clean", r.clean)
        if (r.corrected != null) put("corrected", r.corrected)
        put("vote", r.vote); put("target", r.target)
        if (r.error != null) put("error", r.error)
    }

    private fun fromJson(line: String): TakeRecord? = try {
        val o = JSONObject(line)
        TakeRecord(
            id = o.optLong("id"), ts = o.optLong("ts"),
            model = o.optString("model"), lang = o.optString("lang"),
            audioS = o.optDouble("audio_s").toFloat(), decodeMs = o.optLong("decode_ms"),
            rtf = o.optDouble("rtf").toFloat(), chars = o.optInt("chars"),
            raw = o.optString("raw"), clean = o.optString("clean"),
            corrected = if (o.has("corrected")) o.optString("corrected") else null,
            vote = o.optInt("vote"), target = o.optString("target"),
            error = if (o.has("error")) o.optString("error") else null,
        )
    } catch (_: Throwable) {
        null
    }
}
