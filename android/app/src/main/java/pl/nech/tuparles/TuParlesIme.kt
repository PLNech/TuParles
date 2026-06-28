package pl.nech.tuparles

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.inputmethodservice.InputMethodService
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import pl.nech.domovoy.analytics.DomovoyAnalytics

/**
 * TuParles as a system keyboard (InputMethodService). This is what makes the STT
 * app-agnostic: selected as the active input method, its mic commits postprocessed
 * text into the focused field of ANY app via the InputConnection. It shares the
 * exact decode path (Dictation), model loader (Models), settings, logging, and
 * telemetry with the rest of the app — the keyboard is a thin surface over the same
 * core, never a fork.
 *
 * Interaction: tap the mic to start, tap again to stop; the take is decoded
 * (whisper.cpp) and cleaned (pipeline.postprocess) off the main thread, then
 * committed. A control row gives backspace / space / newline, a language cycle, and
 * a switch back to your previous keyboard. RECORD_AUDIO must already be granted (via
 * the TuParles app) — an IME can't run the permission dialog itself.
 */
class TuParlesIme : InputMethodService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val recorder = AudioRecorder()

    private lateinit var status: TextView
    private lateinit var mic: Button

    @Volatile private var recording = false
    @Volatile private var busy = false // decoding — block re-entry

    override fun onCreateInputView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#11161C"))
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }

        status = TextView(this).apply {
            textSize = 13f
            setTextColor(Color.parseColor("#9FB3C8"))
            setPadding(dp(6), dp(2), dp(6), dp(8))
        }
        root.addView(status)

        mic = Button(this).apply {
            isAllCaps = false
            textSize = 18f
            text = "🎙  Parler"
            setOnClickListener { onMicTapped() }
        }
        root.addView(mic, lp(matchW = true, heightDp = 96))

        // Control row: backspace · space · newline · langue · switch keyboard.
        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        controls.addView(key("⌫") { ic()?.deleteSurroundingText(1, 0) }, weight())
        controls.addView(key("espace") { ic()?.commitText(" ", 1) }, weight(2f))
        controls.addView(key("⏎") { onEnter() }, weight())
        controls.addView(key(langGlyph()) { cycleLang() }.also { langKey = it }, weight())
        controls.addView(key("⌨") { switchAway() }, weight())
        root.addView(controls, lp(matchW = true))

        refreshStatus("prêt")
        return root
    }

    private var langKey: Button? = null

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        // Lazy-load the model the first time the keyboard is shown.
        if (!Engine.ready) {
            refreshStatus("chargement du modèle…")
            scope.launch {
                try {
                    Models.ensureLoaded(this@TuParlesIme)
                    refreshStatus("prêt")
                } catch (e: Throwable) {
                    DebugLog.e(TAG, "ime: model load failed", e)
                    refreshStatus("⚠️ modèle indisponible")
                }
            }
        } else {
            refreshStatus("prêt")
        }
    }

    private fun onMicTapped() {
        if (busy) return
        if (!recording) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED
            ) {
                refreshStatus("🎙 ouvre l'app TuParles pour autoriser le micro")
                return
            }
            if (!Engine.ready) {
                refreshStatus("modèle pas encore prêt…")
                return
            }
            recorder.start()
            recording = true
            mic.text = "■  Stop"
            mic.setBackgroundColor(Color.parseColor("#C62828"))
            refreshStatus("🔴 enregistrement…")
            DomovoyAnalytics.action("ime_record_start")
        } else {
            val samples = recorder.stop()
            recording = false
            mic.text = "🎙  Parler"
            mic.setBackgroundColor(Color.TRANSPARENT)
            decodeAndCommit(samples)
        }
    }

    private fun decodeAndCommit(samples: ShortArray) {
        if (samples.isEmpty()) {
            refreshStatus("⚠️ audio vide (micro ?)")
            return
        }
        busy = true
        mic.isEnabled = false
        refreshStatus("⏳ décodage (%.1fs)…".format(samples.size.toFloat() / SAMPLE_RATE))
        scope.launch {
            try {
                val take = Dictation.decode(
                    samples,
                    Settings.lang(this@TuParlesIme),
                    Settings.postprocessOn(this@TuParlesIme),
                )
                val text = take.clean.trim()
                if (text.isNotEmpty()) {
                    // Trailing space so consecutive utterances flow into a sentence.
                    ic()?.commitText("$text ", 1)
                    refreshStatus("✅ ${take.ms}ms · ${text.length} car.")
                    DomovoyAnalytics.action("ime_commit", attributes = mapOf("chars" to text.length.toString()))
                } else {
                    refreshStatus("…rien entendu")
                }
            } catch (e: Throwable) {
                DebugLog.e(TAG, "ime: decode failed", e)
                refreshStatus("⚠️ ${e.message?.take(60)}")
            } finally {
                busy = false
                mic.isEnabled = true
            }
        }
    }

    private fun onEnter() {
        val ic = ic() ?: return
        val info = currentInputEditorInfo
        val action = info?.imeOptions?.and(EditorInfo.IME_MASK_ACTION) ?: EditorInfo.IME_ACTION_NONE
        val noEnterAction = (info?.imeOptions?.and(EditorInfo.IME_FLAG_NO_ENTER_ACTION) ?: 0) != 0
        if (action != EditorInfo.IME_ACTION_NONE && action != EditorInfo.IME_ACTION_UNSPECIFIED && !noEnterAction) {
            ic.performEditorAction(action) // Send / Search / Go in single-line fields
        } else {
            ic.commitText("\n", 1) // multi-line: real newline
        }
    }

    private fun cycleLang() {
        val next = when (Settings.lang(this)) {
            "auto" -> "fr"; "fr" -> "en"; else -> "auto"
        }
        Settings.set(this, Settings.KEY_LANG, next)
        langKey?.text = langGlyph()
        refreshStatus("langue : $next")
    }

    private fun langGlyph(): String = "🌐 ${Settings.lang(this)}"

    private fun switchAway() {
        // Hand control back to the user's previous keyboard.
        if (Build.VERSION.SDK_INT >= 28 && switchToPreviousInputMethod()) return
        (getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)?.showInputMethodPicker()
    }

    private fun refreshStatus(state: String) {
        val model = Engine.loadedFrom.ifEmpty { "—" }
        status.text = "TuParles · $state    ·    $model · ${Settings.lang(this)}"
    }

    private fun ic() = currentInputConnection

    override fun onFinishInput() {
        super.onFinishInput()
        if (recording) {
            recorder.stop()
            recording = false
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    // --- tiny view helpers (programmatic UI, matching the app's style) ---

    private fun key(label: String, onTap: () -> Unit) = Button(this).apply {
        isAllCaps = false
        text = label
        textSize = 16f
        setOnClickListener { onTap() }
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
    }
}
