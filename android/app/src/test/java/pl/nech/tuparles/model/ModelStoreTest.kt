package pl.nech.tuparles.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** The safety gate + storage bookkeeping, on a temp dir (pure java.io). */
class ModelStoreTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun store(): Pair<ModelStore, File> {
        val dir = tmp.newFolder("models")
        return ModelStore(dir) to dir
    }

    /** A tiny custom spec whose sha256 + size match [bytes], so install() can pass verification. */
    private fun specFor(fileName: String, bytes: ByteArray) = ModelSpec(
        id = "test-$fileName",
        fileName = fileName,
        label = fileName,
        character = "test",
        sizeBytes = bytes.size.toLong(),
        sha256 = sha256Of(bytes),
    )

    @Test
    fun install_verifies_then_moves_the_file_into_place() {
        val (store, dir) = store()
        val bytes = "hello whisper".toByteArray()
        val spec = specFor("ggml-x.bin", bytes)
        val staged = tmp.newFile("staged.bin").apply { writeBytes(bytes) }

        assertEquals(ModelStore.InstallResult.OK, store.install(staged, spec))
        assertTrue(store.isInstalled(spec))
        assertEquals(bytes.size.toLong(), File(dir, "ggml-x.bin").length())
        assertFalse("staged copy is consumed", staged.exists())
        assertFalse("no .part left behind", File(dir, "ggml-x.bin.part").exists())
    }

    @Test
    fun install_rejects_a_checksum_mismatch_and_deletes_the_bad_file() {
        val (store, dir) = store()
        val spec = specFor("ggml-x.bin", "the right bytes".toByteArray())
        val staged = tmp.newFile("staged.bin").apply { writeBytes("WRONG bytes here".toByteArray()) }

        // Same length as spec would be needed to reach the sha step; force size match then wrong hash.
        val sameLenWrong = ByteArray(spec.sizeBytes.toInt()) { 0 }
        staged.writeBytes(sameLenWrong)

        assertEquals(ModelStore.InstallResult.CHECKSUM_MISMATCH, store.install(staged, spec))
        assertFalse(store.isInstalled(spec))
        assertFalse("destination never created", File(dir, "ggml-x.bin").exists())
        assertFalse("corrupt staged file deleted", staged.exists())
    }

    @Test
    fun install_rejects_a_size_mismatch() {
        val (store, _) = store()
        val spec = specFor("ggml-x.bin", "0123456789".toByteArray())
        val staged = tmp.newFile("staged.bin").apply { writeBytes("short".toByteArray()) }

        assertEquals(ModelStore.InstallResult.SIZE_MISMATCH, store.install(staged, spec))
        assertFalse(store.isInstalled(spec))
    }

    @Test
    fun installed_ids_reflect_catalog_files_of_the_exact_size() {
        val (store, dir) = store()
        // Sparse files at the exact catalog sizes: isInstalled checks length only.
        sparseFile(File(dir, "ggml-tiny-q5_1.bin"), ModelCatalog.byId("tiny-q5_1")!!.sizeBytes)
        sparseFile(File(dir, "ggml-small.bin"), ModelCatalog.byId("small-f16")!!.sizeBytes)
        // A wrong-size file must NOT count as installed.
        sparseFile(File(dir, "ggml-medium-q5_0.bin"), 123L)

        assertEquals(setOf("tiny-q5_1", "small-f16"), store.installedIds())
        assertFalse(store.isInstalled(ModelCatalog.byId("medium-q5_0")!!))
    }

    @Test
    fun delete_and_total_bytes_used() {
        val (store, dir) = store()
        val tiny = ModelCatalog.byId("tiny-q5_1")!!
        sparseFile(File(dir, tiny.fileName), tiny.sizeBytes)
        assertEquals(tiny.sizeBytes, store.totalBytesUsed())

        assertTrue(store.delete(tiny))
        assertEquals(0L, store.totalBytesUsed())
        assertFalse(store.delete(tiny)) // already gone
    }
}
