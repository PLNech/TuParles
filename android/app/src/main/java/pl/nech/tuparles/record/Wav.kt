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
        val buf = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        for (s in pcm) buf.putShort(s)
        out.write(buf.array())
    }
}
