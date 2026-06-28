package pl.nech.tuparles

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.graphics.Typeface
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.File

// Validating the language=auto fix on base first (fast ~1.5s loop). The FR→EN
// was a hardcoded params.language="en" in the JNI, not model size — base should
// now keep French as French. Step up to small/large for quality once confirmed.
private const val MODEL_NAME = "ggml-base.bin"
const val TAG = "TuParles" // adb logcat -s TuParles to follow the harness
private const val DECODE_TIMEOUT_MS = 90_000L // a runaway decode fails visibly, never hangs forever

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
    @Volatile private var decoding = false // one decode at a time — no stacking
    private lateinit var status: TextView
    private lateinit var liveState: TextView
    private val rows = mutableListOf<PromptRow>()

    // "It's a setting": smart default + total override (TuParles doctrine).
    private var langMode = "auto" // auto-detect FR/EN, or force "fr"/"en"
    private var postprocessOn = true // apply pipeline.postprocess(), or show raw decode

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

        // The live state line: always shows what the harness is doing right now,
        // so a long decode reads as working, not frozen.
        liveState = TextView(this).apply {
            text = "⏸ en attente"
            textSize = 18f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, 28)
        }
        root.addView(liveState)

        // Toggles: language (auto/fr/en) and postprocess (on/off).
        val toggles = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, 24)
        }
        val langBtn = Button(this).apply {
            isAllCaps = false
            text = "Langue : auto"
            setOnClickListener {
                langMode = when (langMode) {
                    "auto" -> "fr"; "fr" -> "en"; else -> "auto"
                }
                text = "Langue : $langMode"
            }
        }
        val ppBtn = Button(this).apply {
            isAllCaps = false
            text = "Postprocess : ON"
            setOnClickListener {
                postprocessOn = !postprocessOn
                text = "Postprocess : ${if (postprocessOn) "ON" else "OFF"}"
            }
        }
        toggles.addView(langBtn)
        toggles.addView(ppBtn)
        root.addView(toggles)

        // Export: hand the takes to an email app addressed to dev@nech.pl.
        root.addView(Button(this).apply {
            isAllCaps = false
            text = "📧 Envoyer mes prises à dev@nech.pl"
            setOnClickListener { shareCaptures() }
        })
        root.addView(TextView(this).apply {
            text = "Prises : Android/data/pl.nech.tuparles/files/captures"
            textSize = 11f
            setTextColor(Color.GRAY)
            setPadding(0, 0, 0, 16)
        })

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

    private fun shareCaptures() {
        val dir = getExternalFilesDir("captures")
        val files = dir?.listFiles()?.filter { it.isFile }.orEmpty()
        if (files.isEmpty()) {
            setState("Aucune prise à envoyer — enregistre d'abord", "#C62828")
            return
        }
        val uris = ArrayList<Uri>()
        for (f in files) {
            uris.add(FileProvider.getUriForFile(this, "pl.nech.tuparles.fileprovider", f))
        }
        val intent = Intent(Intent.ACTION_SEND_MULTIPLE).apply {
            type = "*/*"
            putExtra(Intent.EXTRA_EMAIL, arrayOf("dev@nech.pl"))
            putExtra(Intent.EXTRA_SUBJECT, "TuParles — prises de test (${files.size} fichiers)")
            putExtra(
                Intent.EXTRA_TEXT,
                "Prises de test TuParles : audio (.wav) + transcriptions (results.jsonl).\n" +
                    "Enregistrées sur l'appareil, rien n'a quitté le téléphone avant cet envoi.",
            )
            putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        Log.i(TAG, "share: ${files.size} files → dev@nech.pl")
        startActivity(Intent.createChooser(intent, "Envoyer les prises"))
    }

    private fun setState(s: String, color: String = "#1565C0") {
        liveState.text = s
        liveState.setTextColor(Color.parseColor(color))
    }

    private fun divider() = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 2)
        setBackgroundColor(Color.parseColor("#22000000"))
    }

    private fun loadModel() {
        if (Engine.ready) {
            // recreation re-attaches to the already-loaded model — no reload
            status.text = "Prêt (${Engine.loadedFrom}). ${PROMPTS.size} prompts."
            return
        }
        // Prefer a model pushed to external files (a bigger/better one); else the
        // model bundled in the APK assets keeps it self-contained.
        val pushed = getExternalFilesDir("models")?.listFiles()
            ?.firstOrNull { it.isFile && it.name.endsWith(".bin") }
        lifecycleScope.launch {
            try {
                if (pushed != null) {
                    Log.i(TAG, "model: loading pushed ${pushed.name} (${pushed.length()} bytes)")
                    status.text = "Chargement ${pushed.name} (${pushed.length() / 1_000_000} Mo)…"
                    Engine.ensureModelFromFile(pushed.absolutePath)
                } else {
                    Log.i(TAG, "model: loading bundled asset models/$MODEL_NAME")
                    status.text = "Chargement du modèle intégré…"
                    Engine.ensureModelFromAsset(assets, "models/$MODEL_NAME")
                }
                Log.i(TAG, "model: loaded OK (${Engine.loadedFrom})")
                status.text = "Prêt (${Engine.loadedFrom}). ${PROMPTS.size} prompts."
            } catch (e: Throwable) {
                Log.e(TAG, "model: load FAILED", e)
                status.text = "ERREUR chargement modèle: ${e.message}"
            }
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
            if (decoding) {
                Log.w(TAG, "record#${row.prompt.id}: ignored, a decode is still running")
                setState("⏳ patiente — décodage en cours…", "#EF6C00")
                return
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
            ) {
                ensureMicPermission()
                return
            }
            Log.i(TAG, "record#${row.prompt.id}: start")
            recorder.start()
            recordingRow = row
            row.button.text = "■ Stop"
            row.result.text = ""
            setState("🔴 enregistrement #${row.prompt.id}…", "#C62828")
        } else if (recording === row) {
            val samples = recorder.stop()
            Log.i(TAG, "record#${row.prompt.id}: stop, ${samples.size} samples captured")
            recordingRow = null
            row.button.text = "● Enregistrer"
            row.lastSamples = samples
            decodeAndSave(row, samples)
        } else {
            Log.w(TAG, "record#${row.prompt.id}: ignored, #${recording.prompt.id} still recording")
        }
        // tapping a different row while one records: ignore (one at a time)
    }

    private fun decodeAndSave(row: PromptRow, samples: ShortArray) {
        val id = row.prompt.id
        val ctx = Engine.whisper
        if (ctx == null) {
            Log.w(TAG, "decode#$id: model not loaded yet")
            row.result.text = "modèle pas encore chargé"
            return
        }
        val seconds = samples.size.toFloat() / SAMPLE_RATE
        Log.i(TAG, "decode#$id: ${samples.size} samples (${"%.2f".format(seconds)}s)")
        if (samples.isEmpty()) {
            Log.w(TAG, "decode#$id: EMPTY audio — nothing captured, skipping")
            row.result.text = "audio vide — rien enregistré (mic ?)"
            setState("⚠️ #$id : audio vide", "#C62828")
            return
        }
        row.result.text = ""
        setState("⏳ décodage #$id (%.1fs)…".format(seconds), "#EF6C00")
        decoding = true
        lifecycleScope.launch {
            try {
                // The ONE decode path — same Dictation the IME and scratchpad call,
                // so the harness can't diverge from what users actually get.
                val take = Dictation.decode(samples, langMode, postprocessOn)
                row.result.text = "RAW: ${take.raw}\n\nPOST: ${take.clean}"
                save(row.prompt, samples, seconds, take.raw, take.clean)
                setState("✅ #$id fait en ${take.ms}ms — prochaine prise", "#2E7D32")
            } catch (e: Throwable) {
                DebugLog.e(TAG, "decode#$id FAILED", e)
                row.result.text = "ERREUR: ${e.message}"
                setState("⚠️ erreur #$id : ${e.message}", "#C62828")
            } finally {
                decoding = false
            }
        }
    }

    private fun save(prompt: Prompt, samples: ShortArray, seconds: Float, raw: String, cleaned: String) {
        val dir = getExternalFilesDir("captures")
        if (dir == null) {
            Log.e(TAG, "save#${prompt.id}: getExternalFilesDir(captures) is null")
            return
        }
        Log.i(TAG, "save#${prompt.id}: → ${dir.absolutePath}")
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
