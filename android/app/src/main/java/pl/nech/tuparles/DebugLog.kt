package pl.nech.tuparles

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Full, durable, on-device logging — the "recover after 7 days away" safety net.
 * Tees every TuParles log line to a daily rotating file in getExternalFilesDir("logs"),
 * so a week of dictation is reviewable on return (adb pull, or the in-app Share).
 * Writes are append-only, synchronized, and best-effort: a logging failure must
 * never crash a take. This is the local half of the telemetry story; DomovoySync
 * is the structured, syncable half.
 */
object DebugLog {
    private const val MAX_FILES = 21 // ~3 weeks of daily logs, then prune oldest
    private var dir: File? = null
    private val tsFmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    private val dayFmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    @Volatile private var verbose = false
    @Volatile private var privateMode = false

    fun init(context: Context) {
        dir = context.getExternalFilesDir("logs")?.also { it.mkdirs() }
        prune()
        i("DebugLog", "logging to ${dir?.absolutePath} (verbose=$verbose, private=$privateMode)")
    }

    fun setVerbose(on: Boolean) {
        verbose = on
    }

    /** Private mode: stop writing to the on-disk log (logcat still flows, ephemeral). */
    fun setPrivate(on: Boolean) {
        privateMode = on
    }

    fun i(tag: String, msg: String) {
        Log.i(tag, msg); write("I", tag, msg)
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg); write("W", tag, msg)
    }

    fun e(tag: String, msg: String, t: Throwable? = null) {
        Log.e(tag, msg, t)
        write("E", tag, msg + (t?.let { "\n" + Log.getStackTraceString(it) } ?: ""))
    }

    fun d(tag: String, msg: String) {
        if (verbose) {
            Log.d(tag, msg); write("D", tag, msg)
        }
    }

    @Synchronized
    private fun write(level: String, tag: String, msg: String) {
        if (privateMode) return // private mode: nothing touches disk
        val d = dir ?: return
        try {
            File(d, "tuparles-${dayFmt.format(Date())}.log")
                .appendText("${tsFmt.format(Date())} $level/$tag: $msg\n")
        } catch (_: Throwable) {
            // best-effort: never let logging break a take
        }
    }

    fun logFiles(): List<File> =
        dir?.listFiles { f -> f.isFile && f.name.endsWith(".log") }
            ?.sortedBy { it.name } ?: emptyList()

    private fun prune() {
        val files = logFiles()
        if (files.size > MAX_FILES) {
            files.take(files.size - MAX_FILES).forEach { it.delete() }
        }
    }

    /** Total bytes of all on-disk logs — for the storage readout. */
    fun sizeBytes(): Long = logFiles().sumOf { it.length() }

    /** Delete every on-disk log. Destructive — callers confirm first. */
    @Synchronized
    fun clear(): Int {
        val files = logFiles()
        var n = 0
        files.forEach { if (it.delete()) n++ }
        return n
    }
}
