package pl.nech.tuparles.input

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import pl.nech.tuparles.core.TranscriptionEngine
import pl.nech.tuparles.record.PcmAccumulator
import pl.nech.tuparles.record.SAMPLE_RATE
import javax.inject.Inject

/**
 * The system voice-input backend. Settings → Saisie vocale can pick this,
 * and any app that asks the default recognizer then gets an on-device decode.
 * SwiftKey's own mic does not call this. The TuParles keyboard does its own
 * capture and uses the same engine.
 *
 * Audio never leaves the device. A missing model is an error, not a network hop.
 */
@AndroidEntryPoint
class TuParlesRecognizer : RecognitionService() {

    @Inject lateinit var engine: TranscriptionEngine

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val main = Handler(Looper.getMainLooper())
    private val samples = PcmAccumulator()
    private var record: AudioRecord? = null
    private var reader: Thread? = null
    @Volatile private var listening = false

    override fun onStartListening(recognizerIntent: Intent, callback: Callback) {
        if (!engine.available) {
            Log.i(TAG, "voice input: no model")
            callback.error(SpeechRecognizer.ERROR_SERVER)
            return
        }
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.RECORD_AUDIO)
            != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            callback.error(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)
            return
        }
        stopMic()
        samples.clear()
        listening = true
        goForeground()
        val rec = openMic()
        if (rec == null) {
            listening = false
            stopForegroundAndDone()
            callback.error(SpeechRecognizer.ERROR_AUDIO)
            return
        }
        record = rec
        callback.readyForSpeech(Bundle())
        reader = Thread {
            val chunk = ShortArray(SAMPLE_RATE / 5)
            while (listening) {
                val n = rec.read(chunk, 0, chunk.size)
                if (n > 0) samples.append(chunk, n)
            }
        }.also {
            it.name = "tuparles-voice"
            it.start()
        }
    }

    override fun onStopListening(callback: Callback) {
        val pcm = stopMic()
        scope.launch {
            val text = decode(pcm)
            main.post {
                if (text.isNullOrBlank()) {
                    callback.error(SpeechRecognizer.ERROR_NO_MATCH)
                } else {
                    callback.results(resultBundle(text))
                }
                stopForegroundAndDone()
            }
        }
    }

    override fun onCancel(callback: Callback) {
        stopMic()
        samples.clear()
        stopForegroundAndDone()
    }

    override fun onDestroy() {
        listening = false
        stopMic()
        scope.cancel()
        super.onDestroy()
    }

    private fun decode(pcm: ShortArray): String? {
        if (pcm.isEmpty()) return null
        val floats = FloatArray(pcm.size) { pcm[it] / 32768f }
        return runBlocking {
            engine.transcribeSamplesCommitted(floats)?.text?.trim()
        }
    }

    private fun openMic(): AudioRecord? {
        val min = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (min <= 0) return null
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(min, SAMPLE_RATE * 2),
        )
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            return null
        }
        rec.startRecording()
        return rec
    }

    private fun stopMic(): ShortArray {
        listening = false
        record?.runCatching { stop() }
        reader?.join(2_000)
        reader = null
        record?.release()
        record = null
        val pcm = samples.toShortArray()
        samples.clear()
        return pcm
    }

    private fun goForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm?.getNotificationChannel(CHANNEL) == null) {
            nm?.createNotificationChannel(
                NotificationChannel(CHANNEL, "Dictée", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val notif: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("TuParles")
            .setContentText("Dicte…")
            .setOngoing(true)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 30) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        } else {
            0
        }
        ServiceCompat.startForeground(this, NOTIF_ID, notif, type)
    }

    private fun stopForegroundAndDone() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
    }

    companion object {
        private const val TAG = "TuParles"
        private const val CHANNEL = "dictation"
        private const val NOTIF_ID = 42

        fun resultBundle(text: String): Bundle = Bundle().apply {
            putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(text))
        }
    }
}
