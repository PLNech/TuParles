package pl.nech.tuparles

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * TuParles as the system speech recognizer: set it as the device's voice-input
 * service and the mic-button anywhere (the Gboard/SwiftKey mic, an app's voice
 * search) routes to on-device TuParles instead of the cloud. It records on
 * onStartListening, decodes through the SAME Dictation path every surface shares
 * on onStopListening, and hands the text back via the standard RESULTS_RECOGNITION
 * bundle. A safety cap auto-finishes a stuck session so the mic is never held open.
 *
 * Additive and isolated: it touches nothing else; if a caller misbehaves the worst
 * case is an error callback, and the rest of the app is unaffected.
 */
class TuParlesRecognitionService : RecognitionService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val recorder = AudioRecorder()
    @Volatile private var listening = false
    private var capJob: Job? = null

    override fun onStartListening(recognizerIntent: Intent, listener: Callback) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            listener.error(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS); return
        }
        scope.launch {
            try {
                Models.ensureLoaded(this@TuParlesRecognitionService)
            } catch (e: Throwable) {
                DebugLog.e(TAG, "recognizer: model load failed", e)
                listener.error(SpeechRecognizer.ERROR_SERVER); return@launch
            }
            listener.readyForSpeech(Bundle())
            listening = true
            try {
                recorder.start { level, _ -> if (listening) safeRms(listener, level) }
                listener.beginningOfSpeech()
            } catch (e: Throwable) {
                DebugLog.e(TAG, "recognizer: mic start failed", e)
                listening = false
                listener.error(SpeechRecognizer.ERROR_AUDIO); return@launch
            }
            // Safety: never hold the mic open forever if onStopListening never arrives.
            capJob = scope.launch { delay(MAX_MS); if (listening) finish(listener) }
        }
    }

    override fun onStopListening(listener: Callback) {
        if (listening) finish(listener)
    }

    override fun onCancel(listener: Callback) {
        capJob?.cancel()
        if (listening) {
            listening = false
            runCatching { recorder.stop() }
        }
    }

    private fun finish(listener: Callback) {
        capJob?.cancel()
        listening = false
        listener.endOfSpeech()
        val samples = runCatching { recorder.stop() }.getOrDefault(ShortArray(0))
        scope.launch {
            try {
                val take = Dictation.decode(
                    samples, Settings.lang(this@TuParlesRecognitionService),
                    Settings.postprocessOn(this@TuParlesRecognitionService),
                    Settings.threads(this@TuParlesRecognitionService),
                )
                val results = Bundle().apply {
                    putStringArrayList(
                        SpeechRecognizer.RESULTS_RECOGNITION,
                        arrayListOf(take.clean.trim()),
                    )
                }
                listener.results(results)
                DebugLog.i(TAG, "recognizer: returned ${take.clean.trim().length} car. in ${take.ms}ms")
            } catch (e: Throwable) {
                DebugLog.e(TAG, "recognizer: decode failed", e)
                listener.error(SpeechRecognizer.ERROR_NO_MATCH)
            }
        }
    }

    private fun safeRms(listener: Callback, level: Float) {
        // RMS in [0,1] → the dB-ish range SpeechRecognizer clients expect (~ -2..10).
        runCatching { listener.rmsChanged(level * 12f - 2f) }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "TuParles"
        private const val MAX_MS = 30_000L // safety cap on a single recognition session
    }
}
