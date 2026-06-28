package pl.nech.tuparles

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
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
    data class Decoding(val seconds: Float) : DictationState
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

    override fun onBind(intent: Intent?): IBinder? = null

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
        goForeground("🔴 écoute…")
        recording = true
        _state.value = DictationState.Recording(0L, 0f)
        try {
            recorder.start { level, elapsed ->
                if (recording) _state.value = DictationState.Recording(elapsed, level)
            }
        } catch (e: Throwable) {
            recording = false
            DebugLog.e(TAG, "service: mic start failed", e)
            _state.value = DictationState.Failed(nextId(), target, e.message ?: "mic error")
            stopForegroundAndSelf()
        }
    }

    private fun stopAndDecode() {
        recording = false
        decoding = true
        val samples = recorder.stop()
        val seconds = samples.size.toFloat() / SAMPLE_RATE
        _state.value = DictationState.Decoding(seconds)
        updateNotif("⏳ décodage…")
        val id = nextId()
        scope.launch {
            try {
                val take = Dictation.decode(samples, Settings.lang(this@DictationService),
                    Settings.postprocessOn(this@DictationService))
                record(take, samples, id)
                val done = DictationState.Done(id, target, take)
                lastDone = done
                _state.value = done
            } catch (e: Throwable) {
                DebugLog.e(TAG, "service: decode failed", e)
                _state.value = DictationState.Failed(id, target, e.message ?: "decode error")
            } finally {
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
        ServiceCompat.startForeground(this, NOTIF_ID, notif(text), type)
    }

    private fun updateNotif(text: String) {
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, notif(text))
    }

    private fun stopForegroundAndSelf() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notif(text: String): Notification {
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
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TuParles")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
    }

    override fun onDestroy() {
        if (recording) recorder.stop()
        super.onDestroy()
    }

    companion object {
        const val ACTION_TOGGLE = "pl.nech.tuparles.TOGGLE"
        const val ACTION_STOP = "pl.nech.tuparles.STOP"
        const val EXTRA_TARGET = "target"
        const val TARGET_SCRATCH = "scratch"
        const val TARGET_IME = "ime"
        private const val NOTIF_ID = 1001
        private const val CHANNEL = "dictation"
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
