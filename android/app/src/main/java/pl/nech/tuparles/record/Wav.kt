package pl.nech.tuparles.record

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** whisper.cpp (Phase B) and the desktop pipeline both want 16 kHz mono. */
const val SAMPLE_RATE = 16_000

/**
 * Write a canonical 16-bit PCM mono WAV. The note's audio is the durable artifact:
 * it can be shared, and replayed through the desktop pipeline for a quality pass.
 */
fun writeWav(file: File, pcm: ShortArray, sampleRate: Int = SAMPLE_RATE) {
    val dataBytes = pcm.size * 2
    val byteRate = sampleRate * 2
    RandomAccessFile(file, "rw").use { out ->
        out.setLength(0)
        fun str(s: String) = out.writeBytes(s)
        fun le32(v: Int) = out.write(
            ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v).array(),
        )
        fun le16(v: Int) = out.write(
            ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(v.toShort()).array(),
        )
        str("RIFF"); le32(36 + dataBytes); str("WAVE")
        str("fmt "); le32(16); le16(1); le16(1)
        le32(sampleRate); le32(byteRate); le16(2); le16(16)
        str("data"); le32(dataBytes)
        // Streamed in fixed blocks rather than staged whole: a 2 h take's data section is
        // ~230 MB, and one ByteBuffer that size doubled the take's peak heap for no gain.
        val block = ByteBuffer.allocate(BLOCK_SAMPLES * 2).order(ByteOrder.LITTLE_ENDIAN)
        var i = 0
        while (i < pcm.size) {
            val n = minOf(BLOCK_SAMPLES, pcm.size - i)
            block.clear()
            for (j in 0 until n) block.putShort(pcm[i + j])
            out.write(block.array(), 0, n * 2)
            i += n
        }
    }
}

/** 64 Ki samples = a 128 KB staging block, whatever the take's length. */
private const val BLOCK_SAMPLES = 64 * 1024

/**
 * A WAV that stays valid after every append. The mic thread spills into it while
 * recording, so a service destroyed mid-take still has the audio that reached the
 * mic. A crash between two appends loses at most the unflushed chunk; the header
 * always describes the samples already written.
 */
class GrowingWav(val file: File, private val sampleRate: Int = SAMPLE_RATE) : java.io.Closeable {
    private val out = RandomAccessFile(file, "rw")
    private val lock = Any()
    private var closed = false
    var samples: Int = 0
        private set

    init {
        file.parentFile?.mkdirs()
        synchronized(lock) { writeHeader(0) }
    }

    /** Append the first [n] samples. A no-op once [close] has run. */
    fun append(pcm: ShortArray, n: Int) {
        val take = n.coerceAtMost(pcm.size)
        if (take <= 0) return
        synchronized(lock) {
            if (closed) return
            out.seek(HEADER_BYTES + samples.toLong() * 2)
            val block = ByteBuffer.allocate(minOf(take, BLOCK_SAMPLES) * 2).order(ByteOrder.LITTLE_ENDIAN)
            var i = 0
            while (i < take) {
                val count = minOf(BLOCK_SAMPLES, take - i)
                block.clear()
                for (j in 0 until count) block.putShort(pcm[i + j])
                out.write(block.array(), 0, count * 2)
                i += count
            }
            samples += take
            writeHeader(samples * 2)
        }
    }

    override fun close() {
        synchronized(lock) {
            if (closed) return
            closed = true
            out.close()
        }
    }

    private fun writeHeader(dataBytes: Int) {
        out.seek(0)
        fun str(s: String) = out.writeBytes(s)
        fun le32(v: Int) = out.write(
            ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v).array(),
        )
        fun le16(v: Int) = out.write(
            ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(v.toShort()).array(),
        )
        val byteRate = sampleRate * 2
        str("RIFF"); le32(36 + dataBytes); str("WAVE")
        str("fmt "); le32(16); le16(1); le16(1)
        le32(sampleRate); le32(byteRate); le16(2); le16(16)
        str("data"); le32(dataBytes)
    }
}

/** Samples a [GrowingWav] / [writeWav] file claims in its data chunk. 0 if absent. */
fun wavSampleCount(file: File): Int {
    if (!file.exists() || file.length() < HEADER_BYTES) return 0
    return ((file.length() - HEADER_BYTES) / 2).toInt()
}

private const val HEADER_BYTES = 44L
