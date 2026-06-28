package pl.nech.tuparles

import android.app.Application
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import pl.nech.domovoy.analytics.DomovoyAnalytics
import pl.nech.domovoy.analytics.DomovoyAnalyticsConfig

/**
 * Process bootstrap, shared by every surface. Starts the embedded CPython (so
 * postprocess is ready before the IME or scratchpad decodes), installs durable file
 * logging, and brings up domovoy analytics with a local-first, sync-when-reachable
 * Sink (DomovoySync). All three are process-scoped — the IME service and the
 * activities attach to the same Python, the same log, the same telemetry outbox.
 */
class TuParlesApp : Application() {
    override fun onCreate() {
        super.onCreate()
        DebugLog.setVerbose(Settings.verbose(this))
        DebugLog.init(this)

        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        DebugLog.i(TAG, "python started; core=tuparles.pipeline")

        DomovoyAnalytics.start(
            this,
            DomovoyAnalyticsConfig(
                enabled = Settings.analyticsOn(this),
                devMode = BuildConfig.DEBUG,
                includeStackTrace = true,
                appVersion = BuildConfig.VERSION_NAME,
            ),
            DomovoySync.sink(this),
        )
        DomovoyAnalytics.registerLifecycle(this)
        DomovoyAnalytics.event(
            "app_start",
            mapOf("flavor" to if (BuildConfig.DEBUG) "debug" else "release"),
        )

        // Best-effort sync on launch: if domovoy is reachable (home LAN), ship the
        // backlog now; if we're away, this no-ops and the outbox keeps accumulating.
        Thread { DomovoySync.drain(this) }.apply { isDaemon = true }.start()
    }

    companion object {
        const val TAG = "TuParles"
    }
}
