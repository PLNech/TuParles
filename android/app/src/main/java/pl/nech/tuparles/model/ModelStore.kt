package pl.nech.tuparles.model

import java.io.File
import java.security.MessageDigest

/**
 * The on-disk home of downloaded models: `filesDir/models/<fileName>`. Pure `java.io`
 * + `java.security` so every rule that matters for safety — size + sha256 verification
 * *before* activation, atomic install, corrupt-partial cleanup — is unit-testable on
 * the JVM against a temp directory, no Android required.
 *
 * A model is "installed" only when its file is present *and* its length matches the
 * catalog exactly; a truncated file (interrupted move, half-written) never counts.
 */
class ModelStore(private val modelsDir: File) {

    fun fileFor(spec: ModelSpec): File = File(modelsDir, spec.fileName)

    /** Present and exactly the expected size (cheap; the sha256 is checked at install). */
    fun isInstalled(spec: ModelSpec): Boolean =
        fileFor(spec).let { it.isFile && it.length() == spec.sizeBytes }

    /** Which catalog ids currently have a usable file on disk. */
    fun installedIds(): Set<String> =
        ModelCatalog.models.filter { isInstalled(it) }.map { it.id }.toSet()

    /** Total bytes used by everything under the models dir (installed + any stragglers). */
    fun totalBytesUsed(): Long =
        modelsDir.listFiles()?.filter { it.isFile }?.sumOf { it.length() } ?: 0L

    /** Remove a model's file. Returns true if a file was there and is now gone. */
    fun delete(spec: ModelSpec): Boolean {
        val f = fileFor(spec)
        return if (f.exists()) f.delete() else false
    }

    /**
     * The safety gate: verify [staged] against [spec] (size then sha256) and, only if it
     * passes, move it atomically into place. Returns true on success; on any failure the
     * staged file and any temp are deleted and the destination is left untouched.
     *
     * Cross-filesystem-safe: the bytes are streamed to a `.part` inside [modelsDir] first
     * (DownloadManager stages in external-files, a possibly different mount), then renamed
     * within the dir — an atomic rename on the same filesystem. The destination file only
     * ever exists complete-and-verified.
     */
    fun install(staged: File, spec: ModelSpec): InstallResult {
        if (!staged.isFile) return InstallResult.MISSING
        if (staged.length() != spec.sizeBytes) {
            staged.delete()
            return InstallResult.SIZE_MISMATCH
        }
        val actual = sha256(staged)
        if (!actual.equals(spec.sha256, ignoreCase = true)) {
            staged.delete()
            return InstallResult.CHECKSUM_MISMATCH
        }
        if (!modelsDir.exists() && !modelsDir.mkdirs()) return InstallResult.STORAGE_ERROR

        val dest = fileFor(spec)
        val part = File(modelsDir, spec.fileName + ".part")
        return runCatching {
            part.delete()
            staged.copyTo(part, overwrite = true)
            staged.delete()
            // Same-dir rename: atomic on POSIX; the model appears whole or not at all.
            if (!part.renameTo(dest)) {
                part.delete()
                return InstallResult.STORAGE_ERROR
            }
            InstallResult.OK
        }.getOrElse {
            part.delete()
            InstallResult.STORAGE_ERROR
        }
    }

    /** Lower-case hex sha256 of [file], streamed in chunks (never the whole model in heap). */
    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(1 shl 16)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    enum class InstallResult { OK, MISSING, SIZE_MISMATCH, CHECKSUM_MISMATCH, STORAGE_ERROR }
}
