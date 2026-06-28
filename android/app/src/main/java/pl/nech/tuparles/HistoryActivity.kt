package pl.nech.tuparles

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.text.format.DateUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import pl.nech.domovoy.analytics.DomovoyAnalytics

/**
 * The learning store, made visible. Every take is a row: the cleaned text, its
 * profiling chips (model/lang/RTF/ms), and the three labelling gestures —
 * 👍 / 👎 / ✏️ correct. A vote or correction rewrites the durable TakesStore row
 * (the local learning label {raw, clean, corrected, vote}) and emits a typed
 * `take_label` metric carrying SHAPE ONLY, never the text — the same privacy
 * contract decode telemetry honours. This is where the trip becomes training data.
 *
 * Rendered as a ScrollView of rows (human dictation scale: dozens–hundreds), newest
 * first, capped to the most recent CAP with a note so an unbounded week never OOMs.
 */
class HistoryActivity : AppCompatActivity() {

    private lateinit var list: LinearLayout
    private lateinit var header: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Historique"
        setContentView(buildUi())
        refresh()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(8))
        }
        root.addView(TextView(this).apply {
            text = "🕘 Historique des prises"; textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
        })
        header = TextView(this).apply {
            textSize = 12f; setTextColor(Color.GRAY); setPadding(0, dp(2), 0, dp(8))
        }
        root.addView(header)

        val scroll = ScrollView(this).apply { isFillViewport = true }
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(list)
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(6), 0, 0)
            addView(flatBtn("📤 Exporter JSONL") { exportHistory() }, weight())
            addView(flatBtn("↻ Rafraîchir") { refresh() }, weight())
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return root
    }

    private fun refresh() {
        list.removeAllViews()
        val all = TakesStore.all(this).sortedByDescending { it.ts }
        val shown = all.take(CAP)
        val s = TakesStore.stats(this)
        header.text = "${all.size} prises · 👍 ${s.upvotes}  👎 ${s.downvotes}  ✏️ ${s.corrected} · " +
            "RTF ${"%.2f".format(s.meanRtf)}×" + if (all.size > CAP) "  ·  (${CAP} récentes)" else ""
        if (shown.isEmpty()) {
            list.addView(TextView(this).apply {
                text = "Aucune prise encore.\nDictez, puis revenez voter/corriger ici."
                setTextColor(Color.GRAY); setPadding(dp(4), dp(24), dp(4), 0); gravity = Gravity.CENTER
            })
            return
        }
        for (rec in shown) list.addView(rowView(rec))
    }

    private fun rowView(rec: TakeRecord): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setBackgroundColor(if (rec.error != null) Color.parseColor("#2A1416") else Color.parseColor("#161B22"))
        }
        // meta line
        val ago = DateUtils.getRelativeTimeSpanString(rec.ts, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS)
        card.addView(TextView(this).apply {
            text = "$ago · ${rec.model} · ${rec.lang} · ⏱ ${rec.decodeMs}ms · ${"%.2f".format(rec.rtf)}× · ${rec.chars}c"
            textSize = 11f; setTextColor(Color.parseColor("#7D8CA0"))
        })
        // best current text (corrected wins over clean)
        val best = rec.corrected?.takeIf { it.isNotBlank() } ?: rec.clean
        card.addView(TextView(this).apply {
            text = if (best.isBlank()) "(rien entendu)" else best
            textSize = 16f; setTextColor(Color.parseColor("#E6EDF3")); setPadding(0, dp(4), 0, 0)
            setTextIsSelectable(true)
        })
        // provenance: show what changed, so the label is honest about its source
        rec.error?.let {
            card.addView(sub("⚠️ ${it.take(80)}", "#E5534B"))
        }
        if (!rec.corrected.isNullOrBlank() && rec.corrected != rec.clean) {
            card.addView(sub("↳ modèle disait : ${rec.clean}", "#7D8CA0"))
        } else if (rec.raw != rec.clean && rec.clean.isNotBlank()) {
            card.addView(sub("↳ brut : ${rec.raw}", "#5E6B7E"))
        }
        // action row
        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(8), 0, 0)
        }
        val up = voteBtn("👍", rec.vote > 0)
        val down = voteBtn("👎", rec.vote < 0)
        up.setOnClickListener { vote(rec, if (rec.vote > 0) 0 else 1); refresh() }
        down.setOnClickListener { vote(rec, if (rec.vote < 0) 0 else -1); refresh() }
        actions.addView(up, weight())
        actions.addView(down, weight())
        actions.addView(flatBtn(if (rec.corrected.isNullOrBlank()) "✏️ Corriger" else "✏️ Modifier") {
            correctDialog(rec)
        }, weight(2f))
        actions.addView(flatBtn("📋") { copy(best) }, weight())
        card.addView(actions)

        return LinearLayout(this).apply {
            // wrapper just to give each card a bottom margin
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(8))
            addView(card, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
    }

    private fun correctDialog(rec: TakeRecord) {
        val input = EditText(this).apply {
            setText(rec.corrected?.takeIf { it.isNotBlank() } ?: rec.clean)
            setSelection(text.length)
        }
        AlertDialog.Builder(this)
            .setTitle("Corriger la prise")
            .setMessage("Le texte juste. On apprend de l'écart entre ce que le modèle a dit et votre correction.")
            .setView(input)
            .setPositiveButton("Enregistrer") { _, _ ->
                val fixed = input.text.toString().trim()
                TakesStore.update(this, rec.id, corrected = fixed)
                DomovoyAnalytics.metric("take_label", mapOf(
                    "id" to rec.id, "action" to "correct", "model" to rec.model, "lang" to rec.lang,
                    "orig_chars" to rec.clean.length, "fix_chars" to fixed.length,
                    "edit_distance" to levenshtein(rec.clean, fixed), "vote" to rec.vote,
                ))
                DebugLog.i(TAG, "correct: take ${rec.id} (${rec.clean.length}→${fixed.length}c)")
                refresh()
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun vote(rec: TakeRecord, v: Int) {
        TakesStore.update(this, rec.id, vote = v)
        DomovoyAnalytics.metric("take_label", mapOf(
            "id" to rec.id, "action" to "vote", "vote" to v,
            "model" to rec.model, "lang" to rec.lang, "rtf" to rec.rtf, "chars" to rec.chars,
        ))
        DebugLog.i(TAG, "vote: take ${rec.id} = $v")
    }

    private fun exportHistory() {
        val all = TakesStore.all(this)
        if (all.isEmpty()) { toast("rien à exporter"); return }
        // the file is already JSONL on disk; point the user at the share flow they know
        toast("${all.size} prises dans history/takes.jsonl — « Logs » partage les fichiers")
    }

    private fun copy(text: String) {
        if (text.isBlank()) { toast("vide"); return }
        (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .setPrimaryClip(ClipData.newPlainText("TuParles", text))
        toast("copié")
    }

    // --- view helpers (match the scratchpad's lean programmatic style) ---

    private fun sub(text: String, color: String) = TextView(this).apply {
        this.text = text; textSize = 12f; setTextColor(Color.parseColor(color)); setPadding(0, dp(3), 0, 0)
    }

    private fun voteBtn(label: String, active: Boolean) = Button(this).apply {
        isAllCaps = false; text = label; textSize = 15f
        setBackgroundColor(if (active) Color.parseColor("#1F6FEB") else Color.parseColor("#21262D"))
        setTextColor(Color.WHITE)
    }

    private fun flatBtn(label: String, onTap: () -> Unit) = Button(this).apply {
        isAllCaps = false; text = label; textSize = 13f
        setBackgroundColor(Color.parseColor("#21262D")); setTextColor(Color.parseColor("#E6EDF3"))
        setOnClickListener { onTap() }
    }

    private fun weight(w: Float = 1f) =
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, w)
            .apply { marginStart = dp(3); marginEnd = dp(3) }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val TAG = "TuParles"
        private const val CAP = 300

        /** Compact Levenshtein — the learning signal's magnitude (shape, not content). */
        fun levenshtein(a: String, b: String): Int {
            if (a == b) return 0
            if (a.isEmpty()) return b.length
            if (b.isEmpty()) return a.length
            var prev = IntArray(b.length + 1) { it }
            var cur = IntArray(b.length + 1)
            for (i in 1..a.length) {
                cur[0] = i
                for (j in 1..b.length) {
                    val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                    cur[j] = minOf(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
                }
                val tmp = prev; prev = cur; cur = tmp
            }
            return prev[b.length]
        }
    }
}
