package pl.nech.tuparles

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

private const val MODEL_NAME = "ggml-large-v3-turbo-q5_0.bin"

/**
 * Rung 2+3 — the de-risk harness. Each prompt gets a Record button; on stop we
 * run the SAME two stages the desktop does: whisper.cpp (native, on-device) for
 * the raw decode, then tuparles.pipeline.postprocess() (embedded CPython) for the
 * clean text. Audio + raw + cleaned are saved per take so the operator can
 * adb-pull and judge the FR/EN code-switch quality.
 */
class MainActivity : AppCompatActivity() {

    private val recorder = AudioRecorder()
    private var postprocess: PyObject? = null
    private var recordingRow: PromptRow? = null
    private lateinit var status: TextView
    private val rows = mutableListOf<PromptRow>()

    private inner class PromptRow(val prompt: Prompt) {
        val button = Button(this@MainActivity)
        val result = TextView(this@MainActivity)
        var lastSamples: ShortArray? = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        postprocess = Python.getInstance().getModule("tuparles.pipeline")

        setContentView(buildUi())
        ensureMicPermission()
        loadModel()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 56, 36, 56)
        }
        status = TextView(this).apply {
            text = "TuParles · de-risk harness\nchargement du modèle…"
            textSize = 16f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, 32)
        }
        root.addView(status)

        for (p in PROMPTS) {
            val row = PromptRow(p)
            rows.add(row)

            root.addView(divider())
            root.addView(TextView(this).apply {
                text = "#${p.id} · ${p.dimension}"
                textSize = 12f
                setTextColor(Color.GRAY)
                setPadding(0, 24, 0, 4)
            })
            root.addView(TextView(this).apply {
                text = p.text
                textSize = 15f
                setPadding(0, 0, 0, 8)
            })
            row.button.apply {
                text = "● Enregistrer"
                isAllCaps = false
                setOnClickListener { onRecordTapped(row) }
            }
            root.addView(row.button)
            row.result.apply {
                text = ""
                textSize = 14f
                setTextColor(Color.parseColor("#2E7D32"))
                setPadding(0, 8, 0, 16)
                setTextIsSelectable(true)
            }
            root.addView(row.result)
        }
        return ScrollView(this).apply {
            addView(root, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }
    }

    private fun divider() = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 2)
        setBackgroundColor(Color.parseColor("#22000000"))
    }

    private fun loadModel() {
        val model = File(getExternalFilesDir("models"), MODEL_NAME)
        if (!model.exists()) {
            status.text = "Modèle absent. Pousse-le :\nadb push $MODEL_NAME \n→ ${model.absolutePath}"
            return
        }
        if (Engine.ready) {
            // recreation re-attaches to the already-loaded model — no reload
            status.text = "Prêt. ${PROMPTS.size} prompts — parle, puis l'opérateur récupère les prises."
            return
        }
        lifecycleScope.launch {
            status.text = "Chargement du modèle (${model.length() / 1_000_000} Mo)…"
            Engine.ensureModel(model.absolutePath)
            status.text = "Prêt. ${PROMPTS.size} prompts — parle, puis l'opérateur récupère les prises."
        }
    }

    private fun ensureMicPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }

    private fun onRecordTapped(row: PromptRow) {
        val recording = recordingRow
        if (recording == null) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
            ) {
                ensureMicPermission()
                return
            }
            recorder.start()
            recordingRow = row
            row.button.text = "■ Stop"
            row.result.text = "enregistrement…"
        } else if (recording === row) {
            val samples = recorder.stop()
            recordingRow = null
            row.button.text = "● Enregistrer"
            row.lastSamples = samples
            decodeAndSave(row, samples)
        }
        // tapping a different row while one records: ignore (one at a time)
    }

    private fun decodeAndSave(row: PromptRow, samples: ShortArray) {
        val ctx = Engine.whisper
        if (ctx == null) {
            row.result.text = "modèle pas encore chargé"
            return
        }
        val seconds = samples.size.toFloat() / SAMPLE_RATE
        row.result.text = "décodage… (%.1fs audio)".format(seconds)
        lifecycleScope.launch {
            val raw = withContext(Dispatchers.Default) {
                ctx.transcribeData(samples.toFloats(), printTimestamp = false).trim()
            }
            val cleaned = withContext(Dispatchers.Default) {
                postprocess?.callAttr("postprocess", raw)?.toString() ?: raw
            }
            row.result.text = "RAW: $raw\n\nPOST: $cleaned"
            save(row.prompt, samples, seconds, raw, cleaned)
        }
    }

    private fun save(prompt: Prompt, samples: ShortArray, seconds: Float, raw: String, cleaned: String) {
        val dir = getExternalFilesDir("captures") ?: return
        writeWav(File(dir, "prompt_%02d.wav".format(prompt.id)), samples)
        val record = JSONObject()
            .put("id", prompt.id)
            .put("dimension", prompt.dimension)
            .put("prompt", prompt.text)
            .put("seconds", seconds.toDouble())
            .put("raw", raw)
            .put("cleaned", cleaned)
        File(dir, "results.jsonl").appendText(record.toString() + "\n")
    }
    // No onDestroy release: the model is process-scoped in Engine so it survives
    // Activity recreation. The OS reclaims it when the process ends.
}
