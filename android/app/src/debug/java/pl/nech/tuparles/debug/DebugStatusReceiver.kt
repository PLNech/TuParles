package pl.nech.tuparles.debug

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import pl.nech.tuparles.core.NotesRepository
import kotlin.concurrent.thread

/**
 * Counts for an adb-driven check. The result string is ids, states, and
 * durations. It never includes transcript text.
 *
 *   adb shell am broadcast -a pl.nech.tuparles.debug.STATUS \
 *     -n pl.nech.tuparles.debug/pl.nech.tuparles.debug.DebugStatusReceiver
 */
class DebugStatusReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        val app = context.applicationContext
        thread(name = "debug-status") {
            val summary = try {
                val notes = EntryPointAccessors.fromApplication(
                    app,
                    DebugStatusEntryPoint::class.java,
                ).notes()
                runBlocking {
                    val visible = notes.observeNotes().first()
                    val recording = notes.recordingNotes().size
                    val newest = visible.maxByOrNull { it.createdAt }
                    "visible=${visible.size} recording=$recording " +
                        "newest=${newest?.id ?: 0} state=${newest?.transcriptState ?: "-"} " +
                        "durationS=${newest?.durationS ?: 0f}"
                }
            } catch (e: Throwable) {
                "status-failed ${e.javaClass.simpleName}"
            }
            pending.setResult(Activity.RESULT_OK, summary, null)
            pending.finish()
        }
    }
}

@EntryPoint
@InstallIn(SingletonComponent::class)
interface DebugStatusEntryPoint {
    fun notes(): NotesRepository
}
