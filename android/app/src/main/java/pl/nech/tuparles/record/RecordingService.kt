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
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import pl.nech.tuparles.core.NotesRepository
import pl.nech.tuparles.core.RecorderSession
import pl.nech.tuparles.core.SegmentationSink
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.transcribe.PartialTranscriber
import pl.nech.tuparles.transcribe.RollingTranscriber
import pl.nech.tuparles.transcribe.TranscriptionManager
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
    @Inject lateinit var transcription: TranscriptionManager
    @Inject lateinit var partials: PartialTranscriber
    @Inject lateinit var rolling: RollingTranscriber

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    @Volatile private var recording = false
    private var capJob: Job? = null

    // Set for a rolling recording: the note is created at start (state RECORDING) so its
    // committed segments have a durable home. Zero when the rolling feature is not armed
    // (feature off / no model) — then the note is created post-hoc at stop, exactly as before.
    @Volatile private var activeNoteId: Long = 0
    private var activeWav: File? = null
    @Volatile private var startToken = 0

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
        activeNoteId = 0
        activeWav = null
        val myToken = ++startToken
        stateHolder.set(RecorderState.Recording(0L, 0f))

        // Rolling arms only when the feature is on AND a model is loaded; the note is then
        // created up front so segments persist as they land. The insert is a suspend call, so
        // the whole start runs on the scope — but a segment can't close before ~minSegment of
        // audio, far longer than the insert, so no early segment is ever dropped.
        val onLevel: (Float, Long) -> Unit = { level, elapsed ->
            if (recording) stateHolder.set(RecorderState.Recording(elapsed, level))
        }
        scope.launch {
            try {
                // If the live transcript is wanted but the model is too slow, degrade honestly
                // and tell the UI (a one-line hint), rather than piling decodes behind speech.
                stateHolder.setLiveDegraded(rolling.isLiveDegraded())
                // The spill file exists before the mic opens, on both paths. A destroyed
                // service then has the audio that reached the mic, not just a hidden row.
                val createdAt = System.currentTimeMillis()
                val file = File(File(filesDir, "notes").apply { mkdirs() }, "note_$createdAt.wav")
                var sink: SegmentationSink? = null
                if (rolling.shouldArm()) {
                    val id = notes.add(
                        Note(
                            wavPath = file.absolutePath,
                            createdAt = createdAt,
                            durationS = 0f,
                            transcriptState = TranscriptState.RECORDING,
                        ),
                    )
                    if (!recording || myToken != startToken) {
                        // Stopped during the insert: don't leave the mic running / a stray note.
                        notes.get(id)?.let { notes.delete(it) }
                        file.delete()
                        return@launch
                    }
                    activeNoteId = id
                    rolling.begin(id)
                    sink = SegmentationSink(SegmentationConfig()) { seg -> rolling.submit(seg) }
                }
                if (!recording || myToken != startToken) {
                    file.delete()
                    return@launch
                }
                activeWav = file
                recorder.start(onLevel, sink, spillTo = file)
                // Live tail preview (#42), now covering only the audio after the last segment.
                partials.start { recorder.snapshotRecentSamples() }
            } catch (e: Throwable) {
                Log.w(TAG, "take arm failed: note=$activeNoteId", e)
                recording = false
                partials.stop()
                rolling.cancel()
                stateHolder.set(RecorderState.Idle)
                stopForegroundAndSelf()
            }
        }
        // Safety cap: a forgotten recording can't hold the mic forever.
        capJob = scope.launch {
            delay(MAX_RECORD_MS)
            if (recording) stopAndSave()
        }
    }

    private fun stopAndSave() {
        if (!recording) return // idempotent: a stop tap racing the safety cap can't double-fire
        capJob?.cancel()
        partials.stop() // end the preview before we release the mic; committed text is durable
        recording = false
        startToken++ // cancel any still-pending start coroutine
        // Honest post-stop state, set the instant the user taps: we are transcribing now, not
        // recording. Show the live-decode backlog (0 when rolling was not armed). The heavy
        // work — the blocking recorder.stop() join + PCM copy, the WAV write, the decode drain —
        // ALL runs on the scope, so the stop tap does zero blocking work on the main thread
        // (stop-button lag, device validation #13).
        val queued = if (activeNoteId != 0L) rolling.pendingCount() else 0
        stateHolder.set(RecorderState.Transcribing(queued))
        updateNotif("💾 transcription…")
        val noteId = activeNoteId
        val wav = activeWav
        scope.launch {
            try {
                val pcm = recorder.stop()
                val remainder = recorder.flushOpenSegment() // tail after the last committed segment
                when {
                    // Rolling path: the spill file already holds the audio. Rewrite the
                    // canonical WAV from the joined buffer, then decode only the remainder.
                    noteId != 0L && pcm.isNotEmpty() && wav != null -> {
                        writeWav(wav, pcm)
                        rolling.finish(remainder, pcm.size.toFloat() / SAMPLE_RATE)
                        logTake("saved", noteId, pcm.size.toFloat() / SAMPLE_RATE, pcm.size)
                    }
                    // Rolling armed but nothing captured (instant stop): drop the empty note.
                    noteId != 0L -> {
                        rolling.cancel()
                        notes.get(noteId)?.let { notes.delete(it) }
                        wav?.delete()
                        logTake("dropped-empty", noteId, 0f, pcm.size)
                    }
                    // Post-hoc path: the spill file is the note. Queue the decode.
                    pcm.isNotEmpty() && wav != null -> {
                        writeWav(wav, pcm)
                        val id = notes.add(
                            Note(
                                wavPath = wav.absolutePath,
                                createdAt = System.currentTimeMillis(),
                                durationS = pcm.size.toFloat() / SAMPLE_RATE,
                                // Enqueued for STT; the manager flips this to RUNNING→DONE,
                                // or leaves it PENDING (waiting for a model) on a lean APK.
                                transcriptState = TranscriptState.PENDING,
                            ),
                        )
                        transcription.onNoteSaved(id)
                        logTake("saved", id, pcm.size.toFloat() / SAMPLE_RATE, pcm.size)
                    }
                    else -> {
                        wav?.delete()
                        logTake("dropped-empty", noteId, 0f, pcm.size)
                    }
                }
            } finally {
                activeNoteId = 0
                activeWav = null
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
        partials.stop()
        // A system screen covering the app, or a low-memory kill, takes this path
        // instead of stop. The spill file already holds the audio; abandon releases
        // the mic without copying the whole take on the main thread. The row leaves
        // RECORDING so the list can show it.
        if (recording) {
            recording = false
            startToken++
            capJob?.cancel()
            val kept = runCatching { recorder.abandon() }.getOrDefault(0)
            rolling.cancel()
            salvage("destroyed-while-recording", pcmSamples = kept)
        }
        super.onDestroy()
    }

    /** Leave a row the list can show, or delete an empty one. */
    private fun salvage(path: String, pcmSamples: Int) {
        val noteId = activeNoteId
        val wav = activeWav
        val samples = maxOf(pcmSamples, wav?.let { wavSampleCount(it) } ?: 0)
        val outcome = runCatching {
            kotlinx.coroutines.runBlocking {
                salvageInterruptedTake(notes, noteId, wav, samples) { id ->
                    transcription.onNoteSaved(id)
                }
            }
        }.getOrElse { e ->
            Log.w(TAG, "salvage failed: note=$noteId pcm=$samples", e)
            "destroyed-while-recording"
        }
        logTake(path, noteId, samples.toFloat() / SAMPLE_RATE, samples)
        activeNoteId = 0
        activeWav = null
    }

    private fun logTake(path: String, noteId: Long, durationS: Float, pcm: Int) {
        Log.i(TAG, "take $path: note=$noteId durationS=$durationS pcm=$pcm")
    }

    companion object {
        const val ACTION_TOGGLE = "pl.nech.tuparles.TOGGLE"
        const val ACTION_START = "pl.nech.tuparles.START"
        const val ACTION_STOP = "pl.nech.tuparles.STOP"
        // 2 h cap — long dictation walks/rides, where 10 min auto-stopped mid-thought.
        // Still a cap: a forgotten recording must not hold the mic forever. The take lives
        // in RAM until stop (the WAV is written once, there), so the ceiling is heap, not
        // time: 2 h @ 16 kHz mono PCM16 = 115.2 M samples, 230 MB in PcmAccumulator, and
        // ~460 MB for the moment stop() hands over its contiguous copy. Comfortable to
        // ~90 min against the largeHeap ceiling; see the manifest note.
        private const val MAX_RECORD_MS = 7_200_000L
        private const val NOTIF_ID = 1001
        private const val CHANNEL = "recording"
        private const val TAG = "TuParles"

        /** Start (or stop, if already recording) a note. */
        fun toggle(c: Context) {
            ContextCompat.startForegroundService(
                c,
                Intent(c, RecordingService::class.java).setAction(ACTION_TOGGLE),
            )
        }
    }
}
