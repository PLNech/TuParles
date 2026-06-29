package pl.nech.tuparles

import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.whispercpp.whisper.WhisperContext
import kotlinx.coroutines.launch
import pl.nech.domovoy.analytics.DomovoyAnalytics

/**
 * The full Réglages screen — the "it's a setting" doctrine made into one place:
 * every behaviour the scratchpad/IME quick-toggles expose, plus the perf knobs that
 * don't fit a quick button (decode threads, verbose logging, analytics opt-out) and
 * a live engine/SIMD readout so "what am I actually running on?" has an answer.
 * Smart defaults everywhere; total override here.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var box: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Réglages"
        val scroll = ScrollView(this)
        box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(28))
        }
        scroll.addView(box)
        setContentView(scroll)
        build()
    }

    private fun build() {
        box.removeAllViews()

        section("Moteur")
        choiceRow("Modèle", Engine.loadedFrom.ifEmpty { "—" }, "Le rung GGML : base intégré (rapide) ou un modèle poussé (précis)") { pickModel() }
        choiceRow("Langue", Settings.lang(this), "auto détecte ; fr/en force la langue") { pickLang() }
        choiceRow("Threads de décodage", threadLabel(), "0 = auto (cœurs perf). Plus = plus rapide, plus de batterie") { pickThreads() }
        choiceRow("Vocabulaire (prompt)", promptLabel(), "biaise l'orthographe de vos termes (pipeline, refactor…) ; ne réécrit pas le sens") { pickPrompt() }
        toggleRow("Post-traitement", "Lexique + corrections fr/en sur le texte décodé",
            Settings.postprocessOn(this)) { Settings.set(this, Settings.KEY_POSTPROCESS, it) }

        section("Vie privée")
        toggleRow("Mode privé", "Coupe TOUT : journaux, analytics, audio. L'échappatoire « jusqu'au retour »",
            Settings.privateMode(this)) {
            Settings.set(this, Settings.KEY_PRIVATE, it); DebugLog.setPrivate(it)
            toast(if (it) "Mode privé ON — rien n'est journalisé ni envoyé" else "Mode privé OFF")
        }
        toggleRow("Sauvegarder l'audio", "Garde le WAV de chaque prise (history/), pour réécouter/ré-évaluer",
            Settings.saveAudio(this)) { Settings.set(this, Settings.KEY_SAVE_AUDIO, it) }
        toggleRow("Analytics domovoy", "Télémétrie typée locale, synchronisée au retour (jamais le texte dicté)",
            Settings.analyticsOn(this)) { Settings.set(this, Settings.KEY_ANALYTICS, it) }
        toggleRow("Journaux verbeux", "Journalisation détaillée — utile pour diagnostiquer après coup",
            Settings.verbose(this)) { Settings.set(this, Settings.KEY_VERBOSE, it) }

        section("Données")
        val audioDir = getExternalFilesDir("takes")
        val audioBytes = audioDir?.listFiles()?.sumOf { it.length() } ?: 0L
        choiceRow("Historique des prises", human(TakesStore.sizeBytes(this)), "takes.jsonl — le magasin d'apprentissage") {
            confirmClear("Effacer l'historique ?", "Supprime takes.jsonl (prises, votes, corrections). Irréversible.") {
                TakesStore.clear(this); toast("historique effacé"); build()
            }
        }
        choiceRow("Audio des prises", human(audioBytes), "les WAV gardés si « Sauvegarder l'audio » est ON") {
            confirmClear("Effacer l'audio ?", "Supprime tous les WAV des prises. Irréversible.") {
                audioDir?.listFiles()?.forEach { it.delete() }; toast("audio effacé"); build()
            }
        }
        choiceRow("Journaux", human(DebugLog.sizeBytes()), "les .log quotidiens (filet de récupération)") {
            confirmClear("Effacer les journaux ?", "Supprime tous les fichiers .log. Irréversible.") {
                val n = DebugLog.clear(); toast("$n journaux effacés"); build()
            }
        }

        section("Système")
        box.addView(TextView(this).apply {
            text = systemInfo(); textSize = 12f; setTextColor(Color.parseColor("#7D8CA0"))
            typeface = Typeface.MONOSPACE; setPadding(0, dp(2), 0, 0)
        })
    }

    // --- pickers ---

    private fun pickModel() {
        val models = Models.available(this)
        val labels = models.map { if (it.sizeMb > 0) "${it.label}  ·  ${it.sizeMb} Mo" else it.label }.toTypedArray()
        val chosen = Settings.model(this)
        val current = models.indexOfFirst { (it.pushed && it.key == chosen) || (!it.pushed && chosen.isEmpty()) }.coerceAtLeast(0)
        AlertDialog.Builder(this).setTitle("Modèle (moteur STT)")
            .setSingleChoiceItems(labels, current) { d, which ->
                d.dismiss()
                val info = models[which]
                toast("chargement ${info.label}…")
                lifecycleScope.launch {
                    try {
                        Models.load(this@SettingsActivity, info); toast("prêt · ${info.label}")
                    } catch (e: Throwable) {
                        DebugLog.e(TAG, "settings: model switch failed", e); toast("⚠️ chargement échoué")
                    } finally { build() }
                }
            }.setNegativeButton("Annuler", null).show()
    }

    private fun pickLang() {
        val opts = arrayOf("auto", "fr", "en")
        AlertDialog.Builder(this).setTitle("Langue")
            .setSingleChoiceItems(opts, opts.indexOf(Settings.lang(this)).coerceAtLeast(0)) { d, which ->
                Settings.set(this, Settings.KEY_LANG, opts[which]); d.dismiss(); build()
            }.show()
    }

    private fun pickThreads() {
        val cores = Runtime.getRuntime().availableProcessors()
        val values = (listOf(0) + (1..cores).toList())
        val labels = values.map { if (it == 0) "Auto (cœurs perf)" else "$it / $cores" }.toTypedArray()
        AlertDialog.Builder(this).setTitle("Threads de décodage")
            .setSingleChoiceItems(labels, values.indexOf(Settings.threads(this)).coerceAtLeast(0)) { d, which ->
                Settings.set(this, Settings.KEY_THREADS, values[which]); d.dismiss(); build()
                DomovoyAnalytics.metric("setting_threads", mapOf("threads" to values[which], "cores" to cores))
            }.show()
    }

    private fun pickPrompt() {
        val input = EditText(this).apply {
            setText(Settings.prompt(this@SettingsActivity))
            hint = "pipeline, refactor, commit, deploy, async…"
            setSelection(text.length)
        }
        AlertDialog.Builder(this)
            .setTitle("Vocabulaire (initial_prompt)")
            .setMessage("Quelques mots/termes que le modèle a tendance à mal orthographier. Laisser vide pour aucun biais.")
            .setView(input)
            .setPositiveButton("Enregistrer") { _, _ ->
                Settings.set(this, Settings.KEY_PROMPT, input.text.toString().trim()); build()
            }
            .setNeutralButton("Effacer") { _, _ -> Settings.set(this, Settings.KEY_PROMPT, ""); build() }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun promptLabel(): String {
        val p = Settings.prompt(this)
        return if (p.isBlank()) "aucun" else if (p.length <= 18) p else p.take(16) + "…"
    }

    private fun threadLabel(): String {
        val t = Settings.threads(this)
        return if (t <= 0) "auto" else "$t / ${Runtime.getRuntime().availableProcessors()}"
    }

    private fun systemInfo(): String {
        val cores = Runtime.getRuntime().availableProcessors()
        val info = try { WhisperContext.getSystemInfo() } catch (_: Throwable) { "indisponible" }
        return "cœurs : $cores\nmoteur : ${Engine.loadedFrom.ifEmpty { "non chargé" }}\nwhisper : $info"
    }

    // --- row builders ---

    private fun section(title: String) {
        box.addView(TextView(this).apply {
            text = title.uppercase(); textSize = 12f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.parseColor("#58A6FF")); setPadding(0, dp(18), 0, dp(6))
        })
    }

    private fun toggleRow(label: String, desc: String, value: Boolean, onChange: (Boolean) -> Unit) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(8), 0, dp(8))
        }
        row.addView(labelBlock(label, desc), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(Switch(this).apply {
            isChecked = value
            setOnCheckedChangeListener { _, checked -> onChange(checked) }
        })
        box.addView(row)
    }

    private fun choiceRow(label: String, value: String, desc: String, onTap: () -> Unit) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(8), 0, dp(8)); isClickable = true; setOnClickListener { onTap() }
        }
        row.addView(labelBlock(label, desc), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(Button(this).apply {
            isAllCaps = false; text = value; textSize = 13f
            setBackgroundColor(Color.parseColor("#21262D")); setTextColor(Color.parseColor("#E6EDF3"))
            setOnClickListener { onTap() }
        })
        box.addView(row)
    }

    private fun labelBlock(label: String, desc: String) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        addView(TextView(this@SettingsActivity).apply {
            text = label; textSize = 15f; setTextColor(Color.parseColor("#E6EDF3"))
        })
        addView(TextView(this@SettingsActivity).apply {
            text = desc; textSize = 11f; setTextColor(Color.parseColor("#7D8CA0")); setPadding(0, dp(1), dp(8), 0)
        })
    }

    private fun confirmClear(title: String, message: String, onConfirm: () -> Unit) {
        AlertDialog.Builder(this).setTitle(title).setMessage(message)
            .setPositiveButton("Effacer") { _, _ -> onConfirm() }
            .setNegativeButton("Annuler", null).show()
    }

    private fun human(bytes: Long): String = humanBytes(bytes)

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val TAG = "TuParles"
    }
}
