package pl.nech.tuparles.input

import android.content.Intent
import androidx.activity.ComponentActivity
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Bundle
import android.speech.RecognizerIntent
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
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
 * What SwiftKey's mic actually starts: ACTION_RECOGNIZE_SPEECH. A floating
 * panel records, decodes on device, and returns the text. The caller inserts
 * it. This is the path FUTO and whisperIME use for keyboards that do not
 * switch IME. Gboard ignores it and calls Google.
 */
@AndroidEntryPoint
class RecognizeSpeechActivity : ComponentActivity() {

    @Inject lateinit var engine: TranscriptionEngine

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val samples = PcmAccumulator()
    private var record: AudioRecord? = null
    private var reader: Thread? = null
    @Volatile private var listening = false
    private var status: TextView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
            gravity = Gravity.CENTER_HORIZONTAL
        }
        status = TextView(this).apply {
            text = "J'écoute…"
            textSize = 18f
        }
        val stop = Button(this).apply {
            text = "Terminer"
            setOnClickListener { finishListening() }
        }
        val cancel = Button(this).apply {
            text = "Annuler"
            setOnClickListener { cancelListening() }
        }
        root.addView(status)
        root.addView(stop)
        root.addView(cancel)
        setContentView(root)
        startListening()
    }

    override fun onDestroy() {
        listening = false
        stopMic()
        scope.cancel()
        super.onDestroy()
    }

    private fun startListening() {
        if (!engine.available) {
            status?.text = "Pas de modèle."
            setResult(RESULT_CANCELED)
            return
        }
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.RECORD_AUDIO)
            != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            status?.text = "Micro refusé. Autorise-le dans TuParles."
            return
        }
        val rec = openMic()
        if (rec == null) {
            status?.text = "Micro occupé."
            return
        }
        record = rec
        listening = true
        reader = Thread {
            val chunk = ShortArray(SAMPLE_RATE / 5)
            while (listening) {
                val n = rec.read(chunk, 0, chunk.size)
                if (n > 0) samples.append(chunk, n)
            }
        }.also {
            it.name = "tuparles-recognize"
            it.start()
        }
    }

    private fun finishListening() {
        val pcm = stopMic()
        status?.text = "Je transcris…"
        scope.launch {
            val text = decode(pcm)
            launch(Dispatchers.Main) {
                val results = text?.let { recognizeSpeechResult(it) }
                if (results == null) {
                    setResult(RESULT_CANCELED)
                } else {
                    setResult(
                        RESULT_OK,
                        Intent().putStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS, results),
                    )
                }
                finish()
            }
        }
    }

    private fun cancelListening() {
        stopMic()
        setResult(RESULT_CANCELED)
        finish()
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
}
