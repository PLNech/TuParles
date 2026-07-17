package pl.nech.tuparles.record

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Read a canonical 16-bit PCM mono WAV back into the normalised float samples
 * whisper.cpp wants ([-1, 1]). The inverse of [writeWav]; kept pure-JVM (no
 * Android) so the audio path feeding the native engine is unit-testable off-device.
 *
 * Robust to a leading `fmt`/`LIST`/`fact` chunk order: it scans the RIFF chunk list
 * for `data` rather than assuming a fixed 44-byte header. PCM16 only (what we record).
 */
fun decodeWavToFloats(file: File): FloatArray = decodeWavToFloats(file.readBytes())

/** ByteArray overload — lets tests decode an in-memory WAV without touching disk. */
fun decodeWavToFloats(bytes: ByteArray): FloatArray {
    require(bytes.size >= 44) { "WAV too small: ${bytes.size} bytes" }
    val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

    require(readTag(buf, 0) == "RIFF") { "not a RIFF file" }
    require(readTag(buf, 8) == "WAVE") { "not a WAVE file" }

    // Walk chunks starting after "RIFF"<size>"WAVE" (offset 12) to find "data".
    var offset = 12
    while (offset + 8 <= bytes.size) {
        val tag = readTag(buf, offset)
        val size = buf.getInt(offset + 4)
        val body = offset + 8
        if (tag == "data") {
            val dataLen = size.coerceAtMost(bytes.size - body)
            val sampleCount = dataLen / 2
            val out = FloatArray(sampleCount)
            var p = body
            for (i in 0 until sampleCount) {
                out[i] = buf.getShort(p) / 32768f
                p += 2
            }
            return out
        }
        // Chunks are word-aligned: an odd size carries a pad byte.
        offset = body + size + (size and 1)
    }
    error("no 'data' chunk found in WAV")
}

private fun readTag(buf: ByteBuffer, at: Int): String =
    buildString(4) { for (i in 0 until 4) append(buf.get(at + i).toInt().toChar()) }
