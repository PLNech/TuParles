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
import android.os.Build
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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import pl.nech.domovoy.analytics.DomovoyAnalytics
import kotlin.math.max
import kotlin.math.min

/**
 * The app's home: a dictation scratchpad and a thin observer of DictationService.
 * The mic toggles the service (compute lives there, not here), so a rotation can't
 * lose a take; this screen just renders the live meter/decoding state and inserts
 * the result. Text + the last-consumed take id are saved across config changes, so
 * neither typed text nor an in-flight decode is ever lost.
 */
class ScratchpadActivity : AppCompatActivity() {

    private lateinit var scratch: EditText
    private lateinit var status: TextView
    private lateinit var mic: Button
    private lateinit var chips: TextView
    private var privBtn: Button? = null
    private var saveBtn: Button? = null
    private var lastConsumedId = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        savedInstanceState?.let {
            scratch.setText(it.getString(K_TEXT, ""))
            scratch.setSelection(scratch.text.length)
            lastConsumedId = it.getLong(K_CONSUMED, 0L)
        }
        ensurePermissions()
        loadModel()
        observeState()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(K_TEXT, scratch.text.toString())
        outState.putLong(K_CONSUMED, lastConsumedId)
    }

    // --- the service-state observer (the heart of the lost-take fix) ---

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                DictationService.state.collect { render(it) }
            }
        }
    }

    private fun render(s: DictationState) {
        when (s) {
        is DictationState.Idle -> {
            mic.text = "🎙  Parler"; mic.isEnabled = true
        }
        is DictationState.Recording -> {
            mic.text = "■  Stop"; mic.isEnabled = true
            setStatus("🔴 ${"%.1f".format(s.elapsedMs / 1000f)}s  ${meter(s.level)}", "#C62828")
        }
        is DictationState.Decoding -> {
            mic.isEnabled = false
            setStatus("⏳ décodage (%.1fs)…".format(s.seconds), "#EF6C00")
        }
        is DictationState.Done -> {
            mic.isEnabled = true
            if (s.target == DictationService.TARGET_SCRATCH && s.id > lastConsumedId) {
                lastConsumedId = s.id
                insertAtCursor(s.take.clean.trim())
                setStatus("✅ ${s.take.ms}ms · ${s.take.clean.trim().length} car.", "#2E7D32")
                updateChips()
            }
        }
        is DictationState.Failed -> {
            mic.isEnabled = true
            if (s.target == DictationService.TARGET_SCRATCH && s.id > lastConsumedId) {
                lastConsumedId = s.id
                setStatus("⚠️ ${s.message.take(60)}", "#C62828")
            }
        }
        }
    }

    private fun onMicTapped() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ensurePermissions(); return
        }
        if (!Engine.ready) {
            setStatus("modèle pas encore prêt…", "#EF6C00"); return
        }
        DictationService.toggle(this, DictationService.TARGET_SCRATCH)
    }

    private fun insertAtCursor(text: String) {
        if (text.isEmpty()) return
        val prevChar = scratch.text.getOrNull(scratch.selectionStart - 1)
        val piece = if (scratch.text.isNotEmpty() && scratch.selectionStart > 0 &&
            prevChar?.isWhitespace() == false
        ) " $text " else "$text "
        val st = max(0, min(scratch.selectionStart, scratch.selectionEnd))
        val en = max(scratch.selectionStart, scratch.selectionEnd).coerceAtLeast(st)
        scratch.text.replace(st, en, piece)
        scratch.setSelection((st + piece.length).coerceAtMost(scratch.text.length))
    }

    // --- UI ---

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(28), dp(20), dp(20))
        }
        root.addView(TextView(this).apply {
            text = "TuParles"; textSize = 22f; setTypeface(typeface, Typeface.BOLD)
        })
        chips = TextView(this).apply {
            textSize = 12f; setTextColor(Color.GRAY); setPadding(0, dp(2), 0, dp(10))
        }
        root.addView(chips)
        status = TextView(this).apply {
            text = "chargement du modèle…"; textSize = 14f
            setTypeface(typeface, Typeface.BOLD); setTextColor(Color.parseColor("#1565C0"))
            setPadding(0, 0, 0, dp(10))
        }
        root.addView(status)
        scratch = EditText(this).apply {
            hint = "Dictez ou tapez ici…"; textSize = 17f
            gravity = Gravity.TOP or Gravity.START
            setTextIsSelectable(true); isVerticalScrollBarEnabled = true
        }
        root.addView(scratch, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        mic = Button(this).apply {
            isAllCaps = false; textSize = 18f; text = "🎙  Parler"
            setOnClickListener { onMicTapped() }
        }
        root.addView(mic, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(72))
            .apply { topMargin = dp(10) })

        root.addView(row(
            btn("📋 Copier") { copyAll() },
            btn("🗑 Effacer") { scratch.setText(""); toast("effacé") },
            btn("📤 Partager") { shareText() },
        ))
        root.addView(row(
            btn("⚙ Modèle") { pickModel() },
            btn("🌐 ${Settings.lang(this)}") { cycleLang() }.also { langBtn = it },
            btn(ppLabel()) { togglePostprocess() }.also { ppBtn = it },
        ))
        root.addView(row(
            btn(privLabel()) { togglePrivate() }.also { privBtn = it },
            btn(saveLabel()) { toggleSaveAudio() }.also { saveBtn = it },
            btn("📊 Stats") { showStats() },
        ))
        root.addView(row(
            btn("🕘 Historique") { startActivity(Intent(this, HistoryActivity::class.java)) },
            btn("⌨ Clavier") { openImeSettings() },
            btn("🎛 Capture") { startActivity(Intent(this, MainActivity::class.java)) },
        ))
        root.addView(row(
            btn("⚙ Réglages") { startActivity(Intent(this, SettingsActivity::class.java)) },
            btn("🧾 Logs") { shareLogs() },
            btn("☁ Sync domovoy") { syncNow() },
        ))
        updateChips()
        return root
    }

    private var langBtn: Button? = null
    private var ppBtn: Button? = null

    // --- text actions ---

    private fun copyAll() {
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .setPrimaryClip(ClipData.newPlainText("TuParles", scratch.text.toString()))
        toast("copié")
        DomovoyAnalytics.metric("scratch_copy", mapOf("chars" to scratch.text.length))
    }

    private fun shareText() {
        val t = scratch.text.toString()
        if (t.isBlank()) { toast("rien à partager"); return }
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"; putExtra(Intent.EXTRA_TEXT, t)
        }, "Partager le texte"))
    }

    // --- settings ---

    private fun pickModel() {
        val models = Models.available(this)
        val labels = models.map { if (it.sizeMb > 0) "${it.label}  ·  ${it.sizeMb} Mo" else it.label }
            .toTypedArray()
        val chosen = Settings.model(this)
        val current = models.indexOfFirst {
            (it.pushed && it.key == chosen) || (!it.pushed && chosen.isEmpty())
        }.coerceAtLeast(0)
        AlertDialog.Builder(this).setTitle("Modèle (moteur STT)")
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
                        mic.isEnabled = true; updateChips()
                    }
                }
            }.setNegativeButton("Annuler", null).show()
    }

    private fun cycleLang() {
        val next = when (Settings.lang(this)) { "auto" -> "fr"; "fr" -> "en"; else -> "auto" }
        Settings.set(this, Settings.KEY_LANG, next); langBtn?.text = "🌐 $next"; updateChips()
    }

    private fun togglePostprocess() {
        Settings.set(this, Settings.KEY_POSTPROCESS, !Settings.postprocessOn(this))
        ppBtn?.text = ppLabel(); updateChips()
    }

    private fun togglePrivate() {
        val on = !Settings.privateMode(this)
        Settings.set(this, Settings.KEY_PRIVATE, on)
        DebugLog.setPrivate(on)
        privBtn?.text = privLabel()
        toast(if (on) "Mode privé ON — rien n'est journalisé ni envoyé" else "Mode privé OFF")
        updateChips()
    }

    private fun toggleSaveAudio() {
        Settings.set(this, Settings.KEY_SAVE_AUDIO, !Settings.saveAudio(this))
        saveBtn?.text = saveLabel()
        toast(if (Settings.saveAudio(this)) "Audio des prises sauvegardé localement" else "Audio non sauvegardé")
    }

    private fun showStats() {
        val s = TakesStore.stats(this)
        val perModel = s.perModel.entries.joinToString("\n") { "   ${it.key}: ${it.value}" }
        AlertDialog.Builder(this).setTitle("📊 Profiling — ${s.n} prises")
            .setMessage(
                "RTF moyen: ${"%.2f".format(s.meanRtf)}×\n" +
                    "Décodage moyen: ${s.meanMs} ms\n" +
                    "Erreurs: ${s.errors}\n" +
                    "👍 ${s.upvotes}  👎 ${s.downvotes}  ✏️ ${s.corrected}\n\n" +
                    "Par modèle:\n$perModel",
            )
            .setPositiveButton("OK", null).show()
    }

    private fun ppLabel() = "✨ PP ${if (Settings.postprocessOn(this)) "ON" else "OFF"}"
    private fun privLabel() = "🔒 Privé ${if (Settings.privateMode(this)) "ON" else "OFF"}"
    private fun saveLabel() = "💾 Audio ${if (Settings.saveAudio(this)) "ON" else "OFF"}"

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
            setStatus(
                if (ok) "☁ synchronisé" else "☁ domovoy injoignable — gardé en local",
                if (ok) "#2E7D32" else "#EF6C00",
            )
        }
    }

    // --- model load ---

    private fun loadModel() {
        if (Engine.ready) { setStatus("prêt", "#2E7D32"); updateChips(); return }
        lifecycleScope.launch {
            try {
                Models.ensureLoaded(this@ScratchpadActivity); setStatus("prêt", "#2E7D32")
            } catch (e: Throwable) {
                DebugLog.e(TAG, "scratch: model load failed", e)
                setStatus("⚠️ modèle indisponible: ${e.message?.take(50)}", "#C62828")
            } finally {
                updateChips()
            }
        }
    }

    private fun ensurePermissions() {
        val needed = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) needed += Manifest.permission.RECORD_AUDIO
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) needed += Manifest.permission.POST_NOTIFICATIONS
        if (needed.isNotEmpty()) ActivityCompat.requestPermissions(this, needed.toTypedArray(), 1)
    }

    // --- helpers ---

    private fun meter(level: Float): String {
        val n = 12
        val filled = (level * n * 3f).toInt().coerceIn(0, n) // boost: speech rarely maxes RMS
        return "█".repeat(filled) + "░".repeat(n - filled)
    }

    private fun updateChips() {
        chips.text = "moteur: ${Engine.loadedFrom.ifEmpty { "—" }}   ·   ${Settings.lang(this)}   ·   ${ppLabel()}" +
            if (Settings.privateMode(this)) "   ·   🔒 PRIVÉ" else ""
    }

    private fun setStatus(s: String, color: String) {
        status.text = s; status.setTextColor(Color.parseColor(color))
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()

    private fun row(vararg buttons: View): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(6), 0, 0)
        for (b in buttons) addView(b, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            .apply { marginStart = dp(3); marginEnd = dp(3) })
    }

    private fun btn(label: String, onTap: () -> Unit) = Button(this).apply {
        isAllCaps = false; text = label; textSize = 13f; setOnClickListener { onTap() }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val TAG = "TuParles"
        private const val K_TEXT = "scratch_text"
        private const val K_CONSUMED = "consumed_id"
    }
}
