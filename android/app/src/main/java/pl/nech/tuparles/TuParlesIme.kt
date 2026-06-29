package pl.nech.tuparles

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.ExtractedTextRequest
import android.view.inputmethod.InputMethodManager
import pl.nech.domovoy.analytics.DomovoyAnalytics
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * TuParles as a system keyboard. It does NOT record or decode itself — it toggles
 * DictationService (compute lives there, lifecycle-independent) and observes the
 * shared state flow: live meter while recording, then commit the result into the
 * focused field of any app. Same core, same telemetry, same model as the scratchpad.
 */
class TuParlesIme : InputMethodService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var status: TextView
    private lateinit var mic: Button
    private var langKey: Button? = null
    private var lastConsumedId = 0L
    // The take last committed into a field — the anchor for "record-fix": after you
    // edit the phrase in another keyboard and come back, tapping 📝 captures the
    // field's final form as this take's correction (the learning label).
    private var fixTakeId = 0L
    private var fixOriginal = ""

    override fun onCreate() {
        super.onCreate()
        // One collector for the service's life — survives input-view recreation.
        scope.launch { DictationService.state.collect { renderState(it) } }
    }

    override fun onCreateInputView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#11161C"))
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }
        status = TextView(this).apply {
            textSize = 13f; setTextColor(Color.parseColor("#9FB3C8"))
            setPadding(dp(6), dp(2), dp(6), dp(8))
        }
        root.addView(status)
        mic = Button(this).apply {
            isAllCaps = false; textSize = 18f; text = "🎙  Parler"
            setOnClickListener { onMicTapped() }
        }
        root.addView(mic, lp(matchW = true, heightDp = 96))

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(8), 0, 0)
        }
        controls.addView(key("⌫") { ic()?.deleteSurroundingText(1, 0) }, weight())
        controls.addView(key("espace") { ic()?.commitText(" ", 1) }, weight(2f))
        controls.addView(key("⏎") { onEnter() }, weight())
        controls.addView(key("📝") { recordFix() }, weight())
        controls.addView(key(langGlyph()) { cycleLang() }.also { langKey = it }, weight())
        controls.addView(key("⌨") { switchAway() }, weight())
        root.addView(controls, lp(matchW = true))

        refreshStatus("prêt")
        return root
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        if (!Engine.ready) {
            refreshStatus("chargement du modèle…")
            scope.launch {
                try {
                    Models.ensureLoaded(this@TuParlesIme); refreshStatus("prêt")
                } catch (e: Throwable) {
                    DebugLog.e(TAG, "ime: model load failed", e); refreshStatus("⚠️ modèle indisponible")
                }
            }
        } else {
            refreshStatus("prêt")
        }
    }

    private fun onMicTapped() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            refreshStatus("🎙 ouvre l'app TuParles pour autoriser le micro"); return
        }
        if (!Engine.ready) {
            refreshStatus("modèle pas encore prêt…"); return
        }
        DictationService.toggle(this, DictationService.TARGET_IME)
    }

    private fun renderState(s: DictationState) {
        if (!::status.isInitialized) return
        when (s) {
            is DictationState.Idle -> { mic.text = "🎙  Parler"; mic.isEnabled = true; refreshStatus("prêt") }
            is DictationState.Recording -> {
                mic.text = "■  Stop"; mic.isEnabled = true
                refreshStatus("🔴 ${"%.1f".format(s.elapsedMs / 1000f)}s  ${meterBar(s.level)}")
            }
            is DictationState.Decoding -> {
                mic.isEnabled = false; refreshStatus("⏳ décodage… ${s.elapsedMs / 1000}s")
            }
            is DictationState.Done -> {
                mic.text = "🎙  Parler"; mic.isEnabled = true
                if (s.target == DictationService.TARGET_IME && s.id > lastConsumedId) {
                    lastConsumedId = s.id
                    val text = s.take.clean.trim()
                    if (text.isNotEmpty()) {
                        ic()?.commitText("$text ", 1)
                        fixTakeId = s.id; fixOriginal = text // anchor for record-fix
                        refreshStatus("✅ ${s.take.ms}ms · ${text.length} car.")
                    } else {
                        refreshStatus("…rien entendu")
                    }
                }
            }
            is DictationState.Failed -> {
                mic.text = "🎙  Parler"; mic.isEnabled = true
                if (s.target == DictationService.TARGET_IME && s.id > lastConsumedId) {
                    lastConsumedId = s.id; refreshStatus("⚠️ ${s.message.take(50)}")
                }
            }
        }
    }

    private fun onEnter() {
        val ic = ic() ?: return
        val info = currentInputEditorInfo
        val action = info?.imeOptions?.and(EditorInfo.IME_MASK_ACTION) ?: EditorInfo.IME_ACTION_NONE
        val noEnterAction = (info?.imeOptions?.and(EditorInfo.IME_FLAG_NO_ENTER_ACTION) ?: 0) != 0
        if (action != EditorInfo.IME_ACTION_NONE && action != EditorInfo.IME_ACTION_UNSPECIFIED && !noEnterAction) {
            ic.performEditorAction(action)
        } else {
            ic.commitText("\n", 1)
        }
    }

    /**
     * Record-fix: the learning loop's return leg. You dictated a phrase, switched to
     * another keyboard to correct it, and came back — tapping 📝 reads the field's
     * final form and stores it as the last take's correction (a {raw, clean, corrected}
     * learning label) plus a typed take_label metric (shape only, never the text).
     * Honest by construction: it does nothing if there's no anchored take, if the
     * field is unchanged, or in private mode (where the take was never recorded).
     */
    private fun recordFix() {
        if (fixTakeId == 0L) { refreshStatus("📝 dictez d'abord, puis corrigez"); return }
        if (Settings.privateMode(this)) { refreshStatus("🔒 mode privé — non enregistré"); return }
        val field = fieldText().trim()
        if (field.isEmpty()) { refreshStatus("📝 champ vide"); return }
        if (field == fixOriginal.trim()) { refreshStatus("📝 aucun changement"); return }
        TakesStore.update(this, fixTakeId, corrected = field)
        val dist = levenshtein(fixOriginal.trim(), field)
        DomovoyAnalytics.metric("take_label", mapOf(
            "id" to fixTakeId, "action" to "record_fix", "source" to "ime",
            "orig_chars" to fixOriginal.trim().length, "fix_chars" to field.length,
            "edit_distance" to dist,
        ))
        DebugLog.i(TAG, "record-fix: take $fixTakeId corrected (Δ$dist car.)")
        refreshStatus("✅ correction enregistrée (Δ$dist car.)")
        fixTakeId = 0L // consume: one correction per take, no accidental double-record
    }

    /** The field's current full text — the "final form" after edits in any keyboard. */
    private fun fieldText(): String {
        val ic = ic() ?: return ""
        ic.getExtractedText(ExtractedTextRequest(), 0)?.text?.let { return it.toString() }
        // Fallback for fields that refuse extraction: stitch around the cursor.
        val before = ic.getTextBeforeCursor(MAX_FIELD, 0) ?: ""
        val after = ic.getTextAfterCursor(MAX_FIELD, 0) ?: ""
        return "$before$after"
    }

    private fun cycleLang() {
        val next = when (Settings.lang(this)) { "auto" -> "fr"; "fr" -> "en"; else -> "auto" }
        Settings.set(this, Settings.KEY_LANG, next)
        langKey?.text = langGlyph()
        refreshStatus("langue : $next")
    }

    private fun langGlyph(): String = "🌐 ${Settings.lang(this)}"

    private fun switchAway() {
        if (Build.VERSION.SDK_INT >= 28 && switchToPreviousInputMethod()) return
        (getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)?.showInputMethodPicker()
    }

    private fun refreshStatus(state: String) {
        if (!::status.isInitialized) return
        status.text = "TuParles · $state    ·    ${Engine.loadedFrom.ifEmpty { "—" }} · ${Settings.lang(this)}" +
            if (Settings.privateMode(this)) " · 🔒" else ""
    }

    private fun ic() = currentInputConnection

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun key(label: String, onTap: () -> Unit) = Button(this).apply {
        isAllCaps = false; text = label; textSize = 16f; setOnClickListener { onTap() }
    }

    private fun weight(w: Float = 1f) =
        LinearLayout.LayoutParams(0, dp(52), w).apply { marginStart = dp(3); marginEnd = dp(3) }

    private fun lp(matchW: Boolean = false, heightDp: Int = ViewGroup.LayoutParams.WRAP_CONTENT) =
        LinearLayout.LayoutParams(
            if (matchW) ViewGroup.LayoutParams.MATCH_PARENT else ViewGroup.LayoutParams.WRAP_CONTENT,
            if (heightDp > 0) dp(heightDp) else heightDp,
        ).apply { gravity = Gravity.CENTER }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val TAG = "TuParles"
        private const val MAX_FIELD = 5000 // cap the field read; dictation fields are short
    }
}
