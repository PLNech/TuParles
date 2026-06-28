package pl.nech.tuparles

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import pl.nech.domovoy.analytics.DomovoyAnalytics
import java.io.File
import java.util.concurrent.atomic.AtomicLong

/** What the UIs render. Process-scoped, so it survives any one screen's lifecycle. */
sealed interface DictationState {
    data object Idle : DictationState
    data class Recording(val elapsedMs: Long, val level: Float) : DictationState
    data class Decoding(val seconds: Float, val elapsedMs: Long = 0L) : DictationState
    data class Done(val id: Long, val target: String, val take: Take) : DictationState
    data class Failed(val id: Long, val target: String, val message: String) : DictationState
}

/**
 * The compute backbone. Recording AND decoding run here, in a service scope that is
 * independent of any Activity or the IME — so rotating the screen or backgrounding
 * the app can no longer cancel an in-flight take (the lost-take bug). It runs as a
 * foreground service of type `microphone` while active (the proper, Android-14-
 * compliant way to hold the mic, and the source of the recording notification), and
 * publishes a process StateFlow the scratchpad and keyboard observe. Per take it
 * records to the durable history, emits typed metrics, and (opt-in) saves the WAV —
 * all suppressed in private mode.
 */
class DictationService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val recorder = AudioRecorder()
    @Volatile private var recording = false
    @Volatile private var decoding = false
    private var target = "scratch"
    private var capJob: kotlinx.coroutines.Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        // Mirror live state onto any placed home-screen widget for the service's life.
        scope.launch { state.collect { TuParlesWidget.render(this@DictationService, it) } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> {
                val tgt = intent.getStringExtra(EXTRA_TARGET) ?: "scratch"
                when {
                    !recording && !decoding -> startRecording(tgt)
                    recording -> stopAndDecode()
                    else -> {} // decoding: ignore re-entry
                }
            }
            ACTION_STOP -> if (recording) stopAndDecode()
        }
        return START_NOT_STICKY
    }

    private fun startRecording(tgt: String) {
        target = tgt
        // We were launched via startForegroundService, so we MUST call startForeground
        // promptly (else ForegroundServiceDidNotStartInTime) — do it before any bail-out.
        goForeground("🔴 écoute…")
        // The widget + recognizer have no UI to request the mic; fail cleanly here
        // rather than dead-mike, so every entry path surfaces a denied permission.
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            DebugLog.w(TAG, "service: RECORD_AUDIO not granted")
            _state.value = DictationState.Failed(nextId(), tgt, "micro non autorisé — ouvre TuParles")
            stopForegroundAndSelf()
            return
        }
        recording = true
        _state.value = DictationState.Recording(0L, 0f)
        try {
            recorder.start { level, elapsed ->
                if (recording) _state.value = DictationState.Recording(elapsed, level)
            }
            // Safety cap: a forgotten/backgrounded take can't hold the mic forever.
            capJob = scope.launch {
                kotlinx.coroutines.delay(MAX_RECORD_MS)
                if (recording) { DebugLog.w(TAG, "service: recording cap hit, auto-stopping"); stopAndDecode() }
            }
        } catch (e: Throwable) {
            recording = false
            DebugLog.e(TAG, "service: mic start failed", e)
            _state.value = DictationState.Failed(nextId(), target, e.message ?: "mic error")
            stopForegroundAndSelf()
        }
    }

    private fun stopAndDecode() {
        if (!recording) return // idempotent: a stop tap racing the safety cap can't double-decode
        capJob?.cancel()
        recording = false
        decoding = true
        val samples = recorder.stop()
        val seconds = samples.size.toFloat() / SAMPLE_RATE
        _state.value = DictationState.Decoding(seconds, 0L)
        updateNotif("⏳ décodage…")
        val id = nextId()
        val startedAt = System.currentTimeMillis()
        scope.launch {
            // Heartbeat so a long (small/medium) decode reads as alive, not frozen.
            val ticker = scope.launch {
                while (true) {
                    kotlinx.coroutines.delay(400)
                    _state.value = DictationState.Decoding(seconds, System.currentTimeMillis() - startedAt)
                }
            }
            try {
                val take = Dictation.decode(samples, Settings.lang(this@DictationService),
                    Settings.postprocessOn(this@DictationService), Settings.threads(this@DictationService))
                record(take, samples, id)
                if (target == TARGET_WIDGET) deliver(take)
                ticker.cancel() // cancel BEFORE the terminal state so it can't clobber Done
                val done = DictationState.Done(id, target, take)
                lastDone = done
                _state.value = done
            } catch (e: Throwable) {
                ticker.cancel()
                DebugLog.e(TAG, "service: decode failed", e)
                _state.value = DictationState.Failed(id, target, e.message ?: "decode error")
            } finally {
                ticker.cancel()
                decoding = false
                stopForegroundAndSelf()
            }
        }
    }

    /** History + typed metrics + opt-in audio — all gated by private mode. */
    private fun record(take: Take, samples: ShortArray, id: Long) {
        if (Settings.privateMode(this)) {
            DebugLog.d(TAG, "private mode: take not recorded")
            return
        }
        val rtf = if (take.seconds > 0f) take.ms / 1000f / take.seconds else 0f
        TakesStore.append(this, TakeRecord(
            id = id, ts = System.currentTimeMillis(), model = take.model, lang = take.lang,
            audioS = take.seconds, decodeMs = take.ms, rtf = rtf, chars = take.clean.length,
            raw = take.raw, clean = take.clean, target = target,
        ))
        // Typed metric → domovoy duckdb/NLP (numbers as numbers).
        DomovoyAnalytics.metric("take", mapOf(
            "audio_s" to take.seconds, "decode_ms" to take.ms, "rtf" to rtf,
            "chars" to take.clean.length, "model" to take.model, "lang" to take.lang,
            "target" to target, "ok" to true,
        ))
        if (Settings.saveAudio(this)) saveAudio(samples, id)
    }

    /**
     * Deliver a widget-originated take: the widget has no field to commit into, so the
     * text goes to the clipboard (best-effort — some OEMs gate background clipboard
     * writes) AND a tap-to-open notification carrying a preview, so the result reaches
     * the user even if the clipboard write is refused. Runs regardless of private mode:
     * private mode suppresses logging/telemetry/audio, never the user's own result.
     */
    private fun deliver(take: Take) {
        val text = take.clean.trim()
        if (text.isEmpty()) { resultNotif("…rien entendu", null); return }
        try {
            getSystemService(ClipboardManager::class.java)
                ?.setPrimaryClip(ClipData.newPlainText("TuParles", text))
        } catch (t: Throwable) {
            DebugLog.w(TAG, "widget: clipboard write refused (${t.javaClass.simpleName})")
        }
        resultNotif("✅ ${text.length} car. copié", text)
    }

    private fun resultNotif(title: String, preview: String?) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL_RESULT) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_RESULT, "Résultat dictée", NotificationManager.IMPORTANCE_DEFAULT),
            )
        }
        val pi = PendingIntent.getActivity(
            this, 1, Intent(this, ScratchpadActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val n = NotificationCompat.Builder(this, CHANNEL_RESULT)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(title)
            .setContentText(preview?.take(120) ?: "")
            .setStyle(preview?.let { NotificationCompat.BigTextStyle().bigText(it.take(400)) })
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        nm.notify(NOTIF_RESULT, n)
    }

    private fun saveAudio(samples: ShortArray, id: Long) {
        val dir = getExternalFilesDir("takes") ?: return
        try {
            writeWav(File(dir, "take_%d.wav".format(id)), samples)
            DebugLog.i(TAG, "take audio saved: take_$id.wav")
        } catch (t: Throwable) {
            DebugLog.w(TAG, "take audio save failed (${t.javaClass.simpleName})")
        }
    }

    // --- foreground notification (mic compliance + visible "TuParles is listening") ---

    private fun goForeground(text: String) {
        val type = if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
        ServiceCompat.startForeground(this, NOTIF_ID, notif(text, showStop = true), type)
    }

    private fun updateNotif(text: String, showStop: Boolean = false) {
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, notif(text, showStop))
    }

    private fun stopForegroundAndSelf() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notif(text: String, showStop: Boolean): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && nm?.getNotificationChannel(CHANNEL) == null) {
            nm?.createNotificationChannel(
                NotificationChannel(CHANNEL, "Dictée", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, ScratchpadActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val b = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TuParles")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pi)
        // While recording, let the user end the take from the shade — no app trip.
        if (showStop) {
            val stop = PendingIntent.getService(
                this, 2, Intent(this, DictationService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            b.addAction(android.R.drawable.ic_media_pause, "Stop", stop)
        }
        return b.build()
    }

    override fun onDestroy() {
        if (recording) recorder.stop()
        // Collector dies with the scope; leave the widget on its resting idle face.
        TuParlesWidget.render(this, DictationState.Idle)
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val ACTION_TOGGLE = "pl.nech.tuparles.TOGGLE"
        const val ACTION_STOP = "pl.nech.tuparles.STOP"
        const val EXTRA_TARGET = "target"
        const val TARGET_SCRATCH = "scratch"
        const val TARGET_IME = "ime"
        const val TARGET_WIDGET = "widget"
        private const val MAX_RECORD_MS = 180_000L // safety cap: a take can't hold the mic forever
        private const val NOTIF_ID = 1001
        private const val NOTIF_RESULT = 1002
        private const val CHANNEL = "dictation"
        private const val CHANNEL_RESULT = "dictation_result"
        private const val TAG = "TuParles"

        private val _state = MutableStateFlow<DictationState>(DictationState.Idle)
        /** Process-scoped state every surface observes — survives any UI's lifecycle. */
        val state: StateFlow<DictationState> = _state

        /** The last completed take, for a surface that (re)binds after a rotation. */
        @Volatile var lastDone: DictationState.Done? = null

        private val seq = AtomicLong(0L)
        private fun nextId(): Long = seq.incrementAndGet()

        /** Start (or stop, if already recording) a take for `target`. */
        fun toggle(c: Context, target: String) {
            ContextCompat.startForegroundService(
                c,
                Intent(c, DictationService::class.java)
                    .setAction(ACTION_TOGGLE)
                    .putExtra(EXTRA_TARGET, target),
            )
        }
    }
}
