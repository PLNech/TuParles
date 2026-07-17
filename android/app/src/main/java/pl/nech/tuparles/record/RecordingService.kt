package pl.nech.tuparles.record

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.RecorderSession
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.ui.MainActivity
import java.io.File
import javax.inject.Inject

/**
 * The recording backbone. Owns the mic in a service scope independent of any
 * Activity, so a note in flight survives screen-off / app-switch (the exact
 * failure that motivated this app). Runs as a foreground service of type
 * `microphone` while active (Android-14-compliant), publishes state via the
 * shared [RecorderStateHolder], and on stop writes the WAV + inserts the [Note].
 */
@AndroidEntryPoint
class RecordingService : Service() {

    @Inject lateinit var recorder: RecorderSession
    @Inject lateinit var notes: NotesRepository
    @Inject lateinit var stateHolder: RecorderStateHolder

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    @Volatile private var recording = false
    private var capJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> if (recording) stopAndSave() else startRecording()
            ACTION_START -> if (!recording) startRecording()
            ACTION_STOP -> if (recording) stopAndSave()
        }
        return START_NOT_STICKY
    }

    private fun startRecording() {
        // Launched via startForegroundService → must startForeground promptly.
        goForeground()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            stateHolder.set(RecorderState.Idle)
            stopForegroundAndSelf()
            return
        }
        recording = true
        stateHolder.set(RecorderState.Recording(0L, 0f))
        try {
            recorder.start { level, elapsed ->
                if (recording) stateHolder.set(RecorderState.Recording(elapsed, level))
            }
            // Safety cap: a forgotten recording can't hold the mic forever.
            capJob = scope.launch {
                delay(MAX_RECORD_MS)
                if (recording) stopAndSave()
            }
        } catch (e: Throwable) {
            recording = false
            stateHolder.set(RecorderState.Idle)
            stopForegroundAndSelf()
        }
    }

    private fun stopAndSave() {
        if (!recording) return // idempotent: a stop tap racing the safety cap can't double-fire
        capJob?.cancel()
        recording = false
        stateHolder.set(RecorderState.Saving)
        updateNotif("💾 enregistrement…")
        val pcm = recorder.stop()
        scope.launch {
            try {
                if (pcm.isNotEmpty()) {
                    val createdAt = System.currentTimeMillis()
                    val dir = File(filesDir, "notes").apply { mkdirs() }
                    val file = File(dir, "note_$createdAt.wav")
                    writeWav(file, pcm)
                    notes.add(
                        Note(
                            wavPath = file.absolutePath,
                            createdAt = createdAt,
                            durationS = pcm.size.toFloat() / SAMPLE_RATE,
                        ),
                    )
                }
            } finally {
                stateHolder.set(RecorderState.Idle)
                stopForegroundAndSelf()
            }
        }
    }

    // --- foreground notification (mic compliance + visible "recording") ---

    private fun goForeground() {
        val type = if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
        ServiceCompat.startForeground(this, NOTIF_ID, notif("🔴 enregistrement en cours", showStop = true), type)
    }

    private fun updateNotif(text: String) {
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, notif(text, showStop = false))
    }

    private fun stopForegroundAndSelf() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notif(text: String, showStop: Boolean): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm?.getNotificationChannel(CHANNEL) == null) {
            nm?.createNotificationChannel(
                NotificationChannel(CHANNEL, "Enregistrement", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val b = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TuParles")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pi)
        if (showStop) {
            val stop = PendingIntent.getService(
                this, 1, Intent(this, RecordingService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            b.addAction(android.R.drawable.ic_media_pause, "Stop", stop)
        }
        return b.build()
    }

    override fun onDestroy() {
        if (recording) recorder.stop()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val ACTION_TOGGLE = "pl.nech.tuparles.TOGGLE"
        const val ACTION_START = "pl.nech.tuparles.START"
        const val ACTION_STOP = "pl.nech.tuparles.STOP"
        private const val MAX_RECORD_MS = 600_000L // 10 min cap
        private const val NOTIF_ID = 1001
        private const val CHANNEL = "recording"

        /** Start (or stop, if already recording) a note. */
        fun toggle(c: Context) {
            ContextCompat.startForegroundService(
                c,
                Intent(c, RecordingService::class.java).setAction(ACTION_TOGGLE),
            )
        }
    }
}
