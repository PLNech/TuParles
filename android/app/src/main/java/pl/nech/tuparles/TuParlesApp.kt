package pl.nech.tuparles

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import pl.nech.tuparles.transcribe.RollingTranscriber
import pl.nech.tuparles.transcribe.TranscriptionManager
import javax.inject.Inject

/** Hilt entry point. On start, recover anything a prior process left mid-flight. */
@HiltAndroidApp
class TuParlesApp : Application() {
    @Inject lateinit var transcription: TranscriptionManager
    @Inject lateinit var rolling: RollingTranscriber

    override fun onCreate() {
        super.onCreate()
        // A recording interrupted by process death: rebuild its transcript from the segments
        // committed so far (and decode the remainder if the WAV reached disk).
        rolling.recover()
        // Notes that never finished their post-hoc decode (or were waiting for a model).
        transcription.resumePending()
    }
}
