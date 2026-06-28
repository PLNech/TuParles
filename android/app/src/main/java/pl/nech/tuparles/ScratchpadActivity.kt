package pl.nech.tuparles

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.provider.Settings as AndroidSettings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import pl.nech.domovoy.analytics.DomovoyAnalytics
import kotlin.math.max
import kotlin.math.min

/**
 * The app's home: a dictation scratchpad. Speak into a real text field, watch it
 * land, copy/clear/share it. Doubles as the place to pick the model (engine rung),
 * flip language/postprocess, enable the TuParles keyboard, share the durable logs,
 * and force a domovoy sync. Same Dictation/Models/Settings core as the IME — this
 * is just the surface you reach for when you're not in another app.
 */
class ScratchpadActivity : AppCompatActivity() {

    private val recorder = AudioRecorder()
    private lateinit var scratch: EditText
    private lateinit var status: TextView
    private lateinit var mic: Button
    private lateinit var chips: TextView
    @Volatile private var recording = false
    @Volatile private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        ensureMicPermission()
        loadModel()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(28), dp(20), dp(20))
        }

        root.addView(TextView(this).apply {
            text = "TuParles"
            textSize = 22f
            setTypeface(typeface, Typeface.BOLD)
        })
        chips = TextView(this).apply {
            textSize = 12f
            setTextColor(Color.GRAY)
            setPadding(0, dp(2), 0, dp(10))
        }
        root.addView(chips)

        status = TextView(this).apply {
            text = "chargement du modèle…"
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.parseColor("#1565C0"))
            setPadding(0, 0, 0, dp(10))
        }
        root.addView(status)

        scratch = EditText(this).apply {
            hint = "Dictez ou tapez ici…"
            textSize = 17f
            gravity = Gravity.TOP or Gravity.START
            setTextIsSelectable(true)
            isVerticalScrollBarEnabled = true
        }
        root.addView(scratch, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f,
        ))

        mic = Button(this).apply {
            isAllCaps = false
            textSize = 18f
            text = "🎙  Parler"
            setOnClickListener { onMicTapped() }
        }
        root.addView(mic, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(72),
        ).apply { topMargin = dp(10) })

        // Text actions.
        root.addView(row(
            btn("📋 Copier") { copyAll() },
            btn("🗑 Effacer") { scratch.setText(""); toast("effacé") },
            btn("📤 Partager") { shareText() },
        ))

        // Engine + behaviour settings.
        root.addView(row(
            btn("⚙ Modèle") { pickModel() }.also { modelBtn = it },
            btn("🌐 ${Settings.lang(this)}") { cycleLang() }.also { langBtn = it },
            btn(ppLabel()) { togglePostprocess() }.also { ppBtn = it },
        ))

        // App plumbing: enable keyboard, capture harness, logs, sync.
        root.addView(row(
            btn("⌨ Clavier") { openImeSettings() },
            btn("🎛 Capture") { startActivity(Intent(this, MainActivity::class.java)) },
        ))
        root.addView(row(
            btn("🧾 Logs") { shareLogs() },
            btn("☁ Sync domovoy") { syncNow() },
        ))

        updateChips()
        return root
    }

    private var modelBtn: Button? = null
    private var langBtn: Button? = null
    private var ppBtn: Button? = null

    // --- dictation ---

    private fun onMicTapped() {
        if (busy) return
        if (!recording) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
            ) {
                ensureMicPermission(); return
            }
            if (!Engine.ready) {
                setStatus("modèle pas encore prêt…", "#EF6C00"); return
            }
            recorder.start()
            recording = true
            mic.text = "■  Stop"
            setStatus("🔴 enregistrement…", "#C62828")
            DomovoyAnalytics.action("scratch_record_start")
        } else {
            val samples = recorder.stop()
            recording = false
            mic.text = "🎙  Parler"
            decodeAndInsert(samples)
        }
    }

    private fun decodeAndInsert(samples: ShortArray) {
        if (samples.isEmpty()) {
            setStatus("⚠️ audio vide (micro ?)", "#C62828"); return
        }
        busy = true
        mic.isEnabled = false
        setStatus("⏳ décodage (%.1fs)…".format(samples.size.toFloat() / SAMPLE_RATE), "#EF6C00")
        lifecycleScope.launch {
            try {
                val take = Dictation.decode(samples, Settings.lang(this@ScratchpadActivity),
                    Settings.postprocessOn(this@ScratchpadActivity))
                insertAtCursor(take.clean.trim())
                setStatus("✅ ${take.ms}ms · ${take.clean.trim().length} car.", "#2E7D32")
            } catch (e: Throwable) {
                DebugLog.e(TAG, "scratch: decode failed", e)
                setStatus("⚠️ ${e.message?.take(60)}", "#C62828")
            } finally {
                busy = false
                mic.isEnabled = true
            }
        }
    }

    private fun insertAtCursor(text: String) {
        if (text.isEmpty()) return
        val piece = if (scratch.text.isNotEmpty() && scratch.selectionStart > 0 &&
            scratch.text.getOrNull(scratch.selectionStart - 1)?.isWhitespace() == false
        ) " $text " else "$text "
        val s = max(0, min(scratch.selectionStart, scratch.selectionEnd))
        val e = max(scratch.selectionStart, scratch.selectionEnd).coerceAtLeast(s)
        scratch.text.replace(s, e, piece)
        scratch.setSelection((s + piece.length).coerceAtMost(scratch.text.length))
    }

    // --- text actions ---

    private fun copyAll() {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("TuParles", scratch.text.toString()))
        toast("copié dans le presse-papiers")
        DomovoyAnalytics.action("scratch_copy", attributes = mapOf("chars" to scratch.text.length.toString()))
    }

    private fun shareText() {
        val t = scratch.text.toString()
        if (t.isBlank()) { toast("rien à partager"); return }
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, t)
        }, "Partager le texte"))
    }

    // --- settings ---

    private fun pickModel() {
        val models = Models.available(this)
        val labels = models.map {
            (if (it.sizeMb > 0) "${it.label}  ·  ${it.sizeMb} Mo" else it.label)
        }.toTypedArray()
        val chosen = Settings.model(this)
        val current = models.indexOfFirst {
            (it.pushed && it.key == chosen) || (!it.pushed && chosen.isEmpty())
        }.coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle("Modèle (moteur STT)")
            .setSingleChoiceItems(labels, current) { d, which ->
                d.dismiss()
                val info = models[which]
                setStatus("chargement ${info.label}…", "#1565C0")
                mic.isEnabled = false
                lifecycleScope.launch {
                    try {
                        Models.load(this@ScratchpadActivity, info)
                        setStatus("prêt · ${info.label}", "#2E7D32")
                    } catch (e: Throwable) {
                        DebugLog.e(TAG, "model switch failed", e)
                        setStatus("⚠️ chargement échoué", "#C62828")
                    } finally {
                        mic.isEnabled = true
                        updateChips()
                    }
                }
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun cycleLang() {
        val next = when (Settings.lang(this)) { "auto" -> "fr"; "fr" -> "en"; else -> "auto" }
        Settings.set(this, Settings.KEY_LANG, next)
        langBtn?.text = "🌐 $next"
        updateChips()
    }

    private fun togglePostprocess() {
        Settings.set(this, Settings.KEY_POSTPROCESS, !Settings.postprocessOn(this))
        ppBtn?.text = ppLabel()
        updateChips()
    }

    private fun ppLabel() = "✨ PP ${if (Settings.postprocessOn(this)) "ON" else "OFF"}"

    private fun openImeSettings() {
        startActivity(Intent(AndroidSettings.ACTION_INPUT_METHOD_SETTINGS))
        toast("Active TuParles, puis choisis-le comme clavier")
    }

    // --- logs + telemetry ---

    private fun shareLogs() {
        val files = DebugLog.logFiles()
        if (files.isEmpty()) { toast("aucun log"); return }
        val uris = ArrayList<Uri>(files.map {
            FileProvider.getUriForFile(this, "pl.nech.tuparles.fileprovider", it)
        })
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND_MULTIPLE).apply {
            type = "text/plain"
            putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            putExtra(Intent.EXTRA_SUBJECT, "TuParles — logs (${files.size})")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }, "Partager les logs"))
    }

    private fun syncNow() {
        setStatus("☁ sync domovoy…", "#1565C0")
        lifecycleScope.launch {
            val ok = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                DomovoySync.drain(this@ScratchpadActivity)
            }
            setStatus(if (ok) "☁ synchronisé" else "☁ domovoy injoignable — gardé en local",
                if (ok) "#2E7D32" else "#EF6C00")
        }
    }

    // --- model load on launch ---

    private fun loadModel() {
        if (Engine.ready) { setStatus("prêt", "#2E7D32"); updateChips(); return }
        lifecycleScope.launch {
            try {
                Models.ensureLoaded(this@ScratchpadActivity)
                setStatus("prêt", "#2E7D32")
            } catch (e: Throwable) {
                DebugLog.e(TAG, "scratch: model load failed", e)
                setStatus("⚠️ modèle indisponible: ${e.message?.take(50)}", "#C62828")
            } finally {
                updateChips()
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

    // --- ui helpers ---

    private fun updateChips() {
        chips.text = "moteur: ${Engine.loadedFrom.ifEmpty { "—" }}   ·   langue: ${Settings.lang(this)}" +
            "   ·   ${ppLabel()}"
    }

    private fun setStatus(s: String, color: String) {
        status.text = s
        status.setTextColor(Color.parseColor(color))
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()

    private fun row(vararg buttons: View): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, 0)
            for (b in buttons) addView(b, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginStart = dp(3); marginEnd = dp(3) })
        }

    private fun btn(label: String, onTap: () -> Unit) = Button(this).apply {
        isAllCaps = false
        text = label
        textSize = 13f
        setOnClickListener { onTap() }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val TAG = "TuParles"
    }
}
