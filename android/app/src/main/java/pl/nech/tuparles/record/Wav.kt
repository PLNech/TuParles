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
