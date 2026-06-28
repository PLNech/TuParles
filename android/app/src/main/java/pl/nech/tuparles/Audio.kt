package pl.nech.tuparles

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** whisper.cpp wants 16 kHz mono. */
const val SAMPLE_RATE = 16_000

/**
 * Minimal push-to-talk recorder: start() opens the mic on a background thread and
 * accumulates 16 kHz mono PCM16; stop() returns the captured samples. No VAD, no
 * streaming — this is the de-risk harness, we record a full prompt then decode.
 */
class AudioRecorder {
    private var record: AudioRecord? = null
    @Volatile private var recording = false
    private var thread: Thread? = null
    private val samples = ArrayList<Short>(SAMPLE_RATE * 10)

    /**
     * @param onLevel optional realtime feedback: invoked per audio chunk on the
     *   reader thread with (rms 0..1, elapsedMs) so a surface can paint a live meter
     *   + timer. Lightweight; the StateFlow consumer throttles redraws.
     */
    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO before start()
    fun start(onLevel: ((Float, Long) -> Unit)? = null) {
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
            Log.e(TAG, "AudioRecord NOT initialized (state=${rec.state}); mic denied or busy?")
        }
        samples.clear()
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
                totalRead += n
                if (onLevel != null && n > 0) {
                    var sum = 0.0
                    for (i in 0 until n) {
                        val s = chunk[i].toDouble(); sum += s * s
                    }
                    val rms = (Math.sqrt(sum / n) / 32768.0).toFloat().coerceIn(0f, 1f)
                    onLevel(rms, System.currentTimeMillis() - startedAt)
                }
            }
            Log.i(TAG, "mic: reader thread done, $totalRead samples read")
        }.also { it.start() }
    }

    /** Stops the mic and returns the captured PCM16 samples. */
    fun stop(): ShortArray {
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
}

/** whisper.cpp transcribeData() takes normalised floats in [-1, 1]. */
fun ShortArray.toFloats(): FloatArray =
    FloatArray(size) { this[it] / 32768.0f }

/** Write a canonical 16-bit PCM mono WAV so the take can be pulled and replayed
 *  through the desktop pipeline for a fair comparison. */
fun writeWav(file: File, pcm: ShortArray, sampleRate: Int = SAMPLE_RATE) {
    val dataBytes = pcm.size * 2
    val byteRate = sampleRate * 2
    RandomAccessFile(file, "rw").use { out ->
        out.setLength(0)
        fun str(s: String) = out.writeBytes(s)
        fun le32(v: Int) = out.write(
            ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v).array()
        )
        fun le16(v: Int) = out.write(
            ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(v.toShort()).array()
        )
        str("RIFF"); le32(36 + dataBytes); str("WAVE")
        str("fmt "); le32(16); le16(1); le16(1)
        le32(sampleRate); le32(byteRate); le16(2); le16(16)
        str("data"); le32(dataBytes)
        val buf = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        for (s in pcm) buf.putShort(s)
        out.write(buf.array())
    }
}
