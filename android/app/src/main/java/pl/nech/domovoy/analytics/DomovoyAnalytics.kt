// Vendored verbatim from the Domovoy project's `domovoy-android-analytics` module
// (pl.nech.domovoy.analytics). Same lib the `pl.nech.domovoy` app uses, so TuParles
// telemetry lands in the same durable, local-first, sanitized JSONL shape and syncs
// to domovoy via a TuParles-supplied Sink (see DomovoySync). Keep in sync with
// upstream; transport stays app-side, so the lib itself carries no network code.
package pl.nech.domovoy.analytics

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.Bundle
import android.os.Process
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.io.FileWriter
import java.util.UUID
import kotlin.math.max

object DomovoyAnalytics {
    private const val PREFS = "domovoy_analytics"
    private const val KEY_SESSION_ID = "session_id"
    private const val KEY_SESSION_STARTED_AT = "session_started_at"

    private lateinit var appContext: Context
    private var config = DomovoyAnalyticsConfig(enabled = false)
    private var sink: DomovoyAnalyticsSink? = null
    private var started = false
    private var foregroundActivities = 0
    private var defaultCrashHandler: Thread.UncaughtExceptionHandler? = null
    private val customKeys = linkedMapOf<String, String>()
    private val breadcrumbs = ArrayDeque<String>()
    private val activeSpans = linkedMapOf<String, Long>()
    private val activityStartedAt = linkedMapOf<String, Long>()
    private var foregroundStartedAt = 0L
    private val runId = UUID.randomUUID().toString()

    @JvmStatic
    fun start(context: Context, config: DomovoyAnalyticsConfig, sink: DomovoyAnalyticsSink) {
        if (started) return
        this.appContext = context.applicationContext
        this.config = config
        this.sink = sink
        started = true
        if (!config.enabled) return
        installCrashHandler()
        event("app_process_start", mapOf("app_version" to config.appVersion, "dev_mode" to config.devMode.toString()))
        flush()
    }

    @JvmStatic
    fun registerLifecycle(application: Application) {
        application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: Activity, state: Bundle?) {
                breadcrumb("activity_created:${activity.javaClass.simpleName}")
            }
            override fun onActivityStarted(activity: Activity) {
                val activityName = activity.javaClass.simpleName
                activityStartedAt[activityName] = System.currentTimeMillis()
                foregroundActivities += 1
                if (foregroundActivities == 1) {
                    foregroundStartedAt = System.currentTimeMillis()
                    event("app_foreground", mapOf("activity" to activityName))
                }
                event("activity_started", mapOf("activity" to activityName), category = "screen")
            }
            override fun onActivityResumed(activity: Activity) {
                val activityName = activity.javaClass.simpleName
                setKey("screen", activityName)
                breadcrumb("screen:$activityName")
            }
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) {
                val activityName = activity.javaClass.simpleName
                val now = System.currentTimeMillis()
                val startedAt = activityStartedAt.remove(activityName) ?: now
                event("activity_stopped", mapOf("activity" to activityName, "duration_ms" to (now - startedAt).coerceAtLeast(0).toString()), category = "screen")
                foregroundActivities = max(0, foregroundActivities - 1)
                if (foregroundActivities == 0) {
                    val foregroundMs = if (foregroundStartedAt > 0L) now - foregroundStartedAt else 0L
                    event("app_background", mapOf("activity" to activityName, "foreground_duration_ms" to foregroundMs.coerceAtLeast(0).toString()))
                    foregroundStartedAt = 0L
                }
            }
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
    }

    @JvmStatic
    fun setKey(key: String, value: String?) {
        if (!started || !config.enabled) return
        val cleanKey = sanitizeToken(key)
        if (cleanKey.isEmpty()) return
        val cleanValue = sanitizeValue(value ?: "")
        if (cleanValue.isEmpty()) customKeys.remove(cleanKey) else customKeys[cleanKey] = cleanValue
        while (customKeys.size > 32) {
            val first = customKeys.keys.firstOrNull() ?: break
            customKeys.remove(first)
        }
    }

    @JvmStatic
    fun breadcrumb(message: String) {
        if (!started || !config.enabled) return
        breadcrumbs.addLast(sanitizeValue(message))
        while (breadcrumbs.size > 24) breadcrumbs.removeFirst()
    }

    /** String-attribute event (back-compat: the Java app + existing callers). */
    @JvmStatic
    fun event(name: String, attributes: Map<String, String> = emptyMap(), category: String = "app", severity: String = "info") {
        emit(name, attributes, category, severity)
    }

    /**
     * Typed-attribute event: values may be Int/Long/Double/Float/Boolean/String (or
     * an enum's .name). They survive to the JSON as native types, so domovoy's
     * duckdb / data-lake / NLP layers can chart numbers as numbers, not strings.
     */
    @JvmStatic
    fun metric(name: String, values: Map<String, Any?> = emptyMap(), category: String = "performance", severity: String = "info") {
        emit(name, values, category, severity)
    }

    private fun emit(name: String, attributes: Map<String, Any?>, category: String, severity: String) {
        if (!started || !config.enabled) return
        val merged = linkedMapOf<String, Any?>()
        merged.putAll(customKeys)
        merged["breadcrumb_count"] = breadcrumbs.size // typed Int
        merged["pid_bucket"] = Process.myPid() % 16 // typed Int
        for ((key, value) in attributes) {
            val k = sanitizeToken(key)
            if (k.isNotEmpty()) merged[k] = if (value is String) sanitizeValue(value) else value
        }
        enqueue(DomovoyAnalyticsEvent(
            observedAtMillis = System.currentTimeMillis(),
            name = sanitizeToken(name).ifEmpty { "event" },
            category = sanitizeToken(category).ifEmpty { "app" },
            severity = sanitizeToken(severity).ifEmpty { "info" },
            sessionId = sessionId(),
            runId = runId,
            attributes = merged,
        ))
        flush()
    }


    @JvmStatic
    fun action(name: String, target: String = "", attributes: Map<String, String> = emptyMap()) {
        val merged = linkedMapOf<String, String>()
        if (target.isNotBlank()) merged["target"] = target
        merged.putAll(attributes)
        breadcrumb("action:$name")
        event("ui_action", merged + mapOf("action" to name), category = "interaction")
    }

    @JvmStatic
    fun startSpan(name: String) {
        if (!started || !config.enabled) return
        val clean = sanitizeToken(name).ifEmpty { "span" }
        activeSpans[clean] = System.currentTimeMillis()
        breadcrumb("span_start:$clean")
    }

    @JvmStatic
    fun finishSpan(name: String, attributes: Map<String, String> = emptyMap()) {
        if (!started || !config.enabled) return
        val clean = sanitizeToken(name).ifEmpty { "span" }
        val startedAt = activeSpans.remove(clean) ?: return
        val durationMs = (System.currentTimeMillis() - startedAt).coerceAtLeast(0)
        val merged = linkedMapOf<String, Any?>("span" to clean, "duration_ms" to durationMs) // typed Long
        merged.putAll(attributes)
        metric("span_finished", merged, category = "performance", severity = if (durationMs > 1500L) "warn" else "info")
    }

    @JvmStatic
    fun flush(): Boolean {
        if (!started || !config.enabled) return false
        val queued = readQueue()
        if (queued.isEmpty()) return true
        val accepted = try { sink?.send(queued) == true } catch (_: Exception) { false }
        if (accepted) writeQueue(emptyList())
        return accepted
    }

    private fun installCrashHandler() {
        if (defaultCrashHandler != null) return
        defaultCrashHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            val attrs = linkedMapOf(
                "thread" to sanitizeValue(thread.name),
                "exception_class" to sanitizeValue(throwable.javaClass.name),
                "message_hash" to Integer.toHexString((throwable.message ?: "").hashCode()),
                "breadcrumbs" to breadcrumbs.size.toString(),
                "active_spans" to activeSpans.keys.joinToString(",").take(180),
            )
            if (config.includeStackTrace && config.devMode) {
                attrs["stacktrace"] = sanitizeValue(throwable.stackTraceToString(), 6000)
            }
            event("app_crash", attrs, category = "crash", severity = "fatal")
            flush()
            defaultCrashHandler?.uncaughtException(thread, throwable)
        }
    }

    private fun enqueue(event: DomovoyAnalyticsEvent) {
        val rows = readQueue().toMutableList()
        rows.add(event)
        while (rows.size > config.maxQueuedEvents) rows.removeAt(0)
        writeQueue(rows)
    }

    private fun queueFile(): File = File(appContext.filesDir, "analytics/events.jsonl")

    private fun readQueue(): List<DomovoyAnalyticsEvent> {
        val file = queueFile()
        if (!file.exists()) return emptyList()
        val rows = ArrayList<DomovoyAnalyticsEvent>()
        try {
            BufferedReader(FileReader(file)).use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isBlank()) continue
                    val json = JSONObject(line)
                    val attrsJson = json.optJSONObject("attributes") ?: JSONObject()
                    val attrs = linkedMapOf<String, Any?>()
                    val keys = attrsJson.keys()
                    while (keys.hasNext()) {
                        val key = keys.next()
                        // get() preserves the native JSON type (number/bool/string).
                        attrs[key] = if (attrsJson.isNull(key)) null else attrsJson.get(key)
                    }
                    rows.add(DomovoyAnalyticsEvent(
                        observedAtMillis = json.optLong("observed_at_ms", System.currentTimeMillis()),
                        name = json.optString("name", "event"),
                        category = json.optString("category", "app"),
                        severity = json.optString("severity", "info"),
                        sessionId = json.optString("session_id", sessionId()),
                        runId = json.optString("run_id", runId),
                        attributes = attrs,
                    ))
                }
            }
        } catch (_: Exception) {
            return emptyList()
        }
        return rows
    }

    private fun writeQueue(rows: List<DomovoyAnalyticsEvent>) {
        val file = queueFile()
        file.parentFile?.mkdirs()
        try {
            FileWriter(file, false).use { writer ->
                for (event in rows) {
                    val json = JSONObject()
                    json.put("observed_at_ms", event.observedAtMillis)
                    json.put("name", event.name)
                    json.put("category", event.category)
                    json.put("severity", event.severity)
                    json.put("session_id", event.sessionId)
                    json.put("run_id", event.runId)
                    val attrs = JSONObject()
                    for ((key, value) in event.attributes) {
                        // JSON has no float; widen to double. null/others -> skip/stringify.
                        when (value) {
                            null -> {}
                            is Float -> attrs.put(key, value.toDouble())
                            is Int, is Long, is Double, is Boolean, is String -> attrs.put(key, value)
                            else -> attrs.put(key, value.toString())
                        }
                    }
                    json.put("attributes", attrs)
                    writer.write(json.toString())
                    writer.write('\n'.code)
                }
            }
        } catch (_: Exception) {
        }
    }

    private fun sessionId(): String {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_SESSION_ID, "") ?: ""
        val startedAt = prefs.getLong(KEY_SESSION_STARTED_AT, 0L)
        val now = System.currentTimeMillis()
        if (existing.isNotEmpty() && now - startedAt < 12L * 60L * 60L * 1000L) return existing
        val next = "app-" + now + "-" + UUID.randomUUID().toString().substring(0, 8)
        prefs.edit().putString(KEY_SESSION_ID, next).putLong(KEY_SESSION_STARTED_AT, now).apply()
        return next
    }

    private fun sanitizeToken(value: String): String = value.lowercase()
        .replace(Regex("[^a-z0-9_.:-]+"), "_")
        .trim('_')
        .take(80)

    private fun sanitizeValue(value: String, maxLen: Int = 180): String = value
        .replace(Regex("[\r\n\t]+"), " ")
        .take(maxLen)
}
