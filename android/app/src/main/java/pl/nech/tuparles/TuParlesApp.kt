package pl.nech.tuparles

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import pl.nech.tuparles.transcribe.TranscriptionManager
import javax.inject.Inject

/** Hilt entry point. On start, resume any transcript left mid-flight by a prior process. */
@HiltAndroidApp
class TuParlesApp : Application() {
    @Inject lateinit var transcription: TranscriptionManager

    override fun onCreate() {
        super.onCreate()
        transcription.resumePending()
    }
}
