package pl.nech.tuparles.input

import android.graphics.Color
import android.inputmethodservice.InputMethodService
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
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
 * A dictation strip, not a full keyboard. Hold the mic, speak, Insérer drops
 * the text at the cursor of whatever field is open. ABC switches back to the
 * previous keyboard (SwiftKey, Gboard, the system one).
 */
@AndroidEntryPoint
class TuParlesKeyboard : InputMethodService() {

    @Inject lateinit var engine: TranscriptionEngine

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val samples = PcmAccumulator()
    private var record: AudioRecord? = null
    private var reader: Thread? = null
    @Volatile private var listening = false

    private var status: TextView? = null
    private var draft: TextView? = null
    private var mic: Button? = null

    override fun onCreateInputView(): View {
        val pad = (12 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
            setBackgroundColor(Color.parseColor("#1B2A4A"))
        }
        status = TextView(this).apply {
            setTextColor(Color.WHITE)
            text = if (engine.available) "Parle, puis Insérer." else "Pas de modèle. Ouvre TuParles pour en télécharger un."
        }
        draft = TextView(this).apply {
            setTextColor(Color.parseColor("#C9D4EE"))
            textSize = 16f
            minHeight = (48 * resources.displayMetrics.density).toInt()
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        mic = button("Micro") { toggleMic() }
        val insert = button("Insérer") { insertDraft() }
        val other = button("ABC") { switchToPreviousInputMethod() }
        row.addView(mic)
        row.addView(insert)
        row.addView(other)
        root.addView(status)
        root.addView(draft)
        root.addView(row)
        return root
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        if (!engine.available) {
            status?.text = "Pas de modèle. Ouvre TuParles pour en télécharger un."
        }
    }

    override fun onDestroy() {
        listening = false
        stopMic()
        scope.cancel()
        super.onDestroy()
    }

    private fun toggleMic() {
        if (listening) {
            val pcm = stopMic()
            status?.text = "Je transcris…"
            mic?.text = "Micro"
            scope.launch {
                val text = decode(pcm)
                launch(Dispatchers.Main) {
                    if (text.isNullOrBlank()) {
                        status?.text = "Rien entendu."
                    } else {
                        draft?.text = text
                        status?.text = "Insérer envoie ça au curseur."
                    }
                }
            }
            return
        }
        if (!engine.available) {
            status?.text = "Pas de modèle. Ouvre TuParles pour en télécharger un."
            return
        }
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.RECORD_AUDIO)
            != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            status?.text = "Micro refusé. Autorise-le dans les réglages de TuParles."
            return
        }
        val rec = openMic()
        if (rec == null) {
            status?.text = "Micro occupé."
            return
        }
        samples.clear()
        record = rec
        listening = true
        mic?.text = "Stop"
        status?.text = "J'écoute…"
        reader = Thread {
            val chunk = ShortArray(SAMPLE_RATE / 5)
            while (listening) {
                val n = rec.read(chunk, 0, chunk.size)
                if (n > 0) samples.append(chunk, n)
            }
        }.also {
            it.name = "tuparles-ime"
            it.start()
        }
    }

    private fun insertDraft() {
        val ic = currentInputConnection
        if (ic == null) {
            status?.text = "Aucun champ."
            return
        }
        val ok = commitDictation({ ic.commitText(it, 1) }, draft?.text?.toString().orEmpty())
        if (ok) {
            draft?.text = ""
            status?.text = "Inséré."
        }
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

    private fun button(label: String, onClick: () -> Unit): Button =
        Button(this).apply {
            text = label
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.parseColor("#243656"))
            gravity = Gravity.CENTER
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
}
