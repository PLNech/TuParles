package pl.nech.tuparles

import android.os.Bundle
import android.view.Gravity
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Rung 1 of the Android spike: prove the Python embed. Chaquopy starts an
 * embedded CPython, imports the SAME `tuparles.pipeline` the desktop daemon
 * uses, and runs `postprocess()` on a hardcoded code-switch string. No engine
 * yet — that's Rung 2 (whisper.cpp via JNI).
 */
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        val py = Python.getInstance()
        val pipeline = py.getModule("tuparles.pipeline")

        val raw = "alors j ai fait un quick refactor du pipeline virgule " +
            "faut que je commit avant la review point"
        val cleaned = pipeline.callAttr("postprocess", raw).toString()

        val body = buildString {
            append("TuParles · Rung 1 — le cœur Python tourne\n\n")
            append("RAW (spoken):\n")
            append(raw)
            append("\n\n")
            append("postprocess():\n")
            append(cleaned)
        }

        val text = TextView(this).apply {
            this.text = body
            textSize = 18f
            gravity = Gravity.START
            setPadding(48, 64, 48, 48)
            setTextIsSelectable(true)
        }
        setContentView(ScrollView(this).apply { addView(text) })
    }
}
