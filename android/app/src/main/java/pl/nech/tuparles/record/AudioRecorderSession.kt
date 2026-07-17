package pl.nech.tuparles.record

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import pl.nech.tuparles.core.RecorderSession
import javax.inject.Inject
import kotlin.math.sqrt

/**
 * Minimal recorder: start() opens the mic on a background thread and accumulates
 * 16 kHz mono PCM16; stop() returns the captured samples. No VAD, no streaming —
 * a dictaphone records a full note, then saves it. Mined from the June POC's Audio.kt.
 */
class AudioRecorderSession @Inject constructor() : RecorderSession {
    private var record: AudioRecord? = null
    @Volatile private var recording = false
    private var thread: Thread? = null
    private val samples = ArrayList<Short>(SAMPLE_RATE * 10)

    // Most-recent audio kept alongside the full capture, for the live-partials preview (#42).
    // Reads never disturb the recording; if nothing ever snapshots it, it costs one array copy.
    private val ring = PcmRingBuffer(SAMPLE_RATE * PARTIAL_WINDOW_S)

    override fun snapshotRecentSamples(): FloatArray = ring.snapshotFloats()

    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO before start()
    override fun start(onLevel: (rms: Float, elapsedMs: Long) -> Unit) {
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufSize = maxOf(minBuf, SAMPLE_RATE * 2) // ~1s headroom
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufSize,
        )
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            // Fail loudly, not silently dead-miked: a revoked permission or a busy mic
            // surfaces as a caught error, not an empty recording.
            Log.e(TAG, "AudioRecord NOT initialized (state=${rec.state}); mic denied or busy?")
            rec.release()
            throw IllegalStateException("micro indisponible (permission ou occupé)")
        }
        samples.clear()
        ring.clear()
        record = rec
        recording = true
        rec.startRecording()
        val startedAt = System.currentTimeMillis()
        Log.i(TAG, "mic: recording (recordingState=${rec.recordingState}, minBuf=$minBuf)")
        thread = Thread {
            val chunk = ShortArray(bufSize / 2)
            var totalRead = 0
            while (recording) {
                val n = rec.read(chunk, 0, chunk.size)
                if (n < 0) {
                    Log.e(TAG, "mic: AudioRecord.read error $n")
                    break
                }
                for (i in 0 until n) samples.add(chunk[i])
                ring.append(chunk, n)
                totalRead += n
                if (n > 0) {
                    var sum = 0.0
                    for (i in 0 until n) {
                        val s = chunk[i].toDouble(); sum += s * s
                    }
                    val rms = (sqrt(sum / n) / 32768.0).toFloat().coerceIn(0f, 1f)
                    onLevel(rms, System.currentTimeMillis() - startedAt)
                }
            }
            Log.i(TAG, "mic: reader thread done, $totalRead samples read")
        }.also { it.start() }
    }

    override fun stop(): ShortArray {
        recording = false
        thread?.join()
        thread = null
        record?.apply {
            stop()
            release()
        }
        record = null
        return ShortArray(samples.size) { samples[it] }
    }

    private companion object {
        const val TAG = "TuParles"
        // How many seconds of recent audio the partials preview sees (#42): the tail only,
        // ~15 s × 16 kHz × 2 B ≈ 480 KB. Not the whole take — reassurance, not a transcript.
        const val PARTIAL_WINDOW_S = 15
    }
}
