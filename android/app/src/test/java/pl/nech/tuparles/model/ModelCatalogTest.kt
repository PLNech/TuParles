package pl.nech.tuparles.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Catalog integrity — the data the whole download subsystem trusts. */
class ModelCatalogTest {

    private val hex64 = Regex("^[0-9a-f]{64}$")

    @Test
    fun urls_are_well_formed_hf_resolve_links_ending_in_the_file_name() {
        for (m in ModelCatalog.models) {
            assertTrue(
                "url must be an HF resolve link: ${m.url}",
                m.url.startsWith("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"),
            )
            assertTrue("url must end in the file name for ${m.id}", m.url.endsWith(m.fileName))
            assertTrue("file name must be a .bin for ${m.id}", m.fileName.endsWith(".bin"))
        }
    }

    @Test
    fun every_sha256_is_lowercase_hex_of_the_right_length() {
        for (m in ModelCatalog.models) {
            assertTrue("bad sha256 for ${m.id}: ${m.sha256}", hex64.matches(m.sha256))
        }
    }

    @Test
    fun every_size_is_positive() {
        for (m in ModelCatalog.models) {
            assertTrue("size must be > 0 for ${m.id}", m.sizeBytes > 0L)
        }
    }

    @Test
    fun catalog_holds_the_expected_seven_rungs_including_the_two_q5_downloads() {
        assertEquals(7, ModelCatalog.models.size)
        val ids = ModelCatalog.models.map { it.id }.toSet()
        // The dotprod-era q5 rungs (added once the app shipped the +dotprod native tier).
        assertTrue("base-q5_1 rung present", "base-q5_1" in ids)
        assertTrue("small-q5_1 rung present", "small-q5_1" in ids)
    }

    @Test
    fun exactly_one_model_is_recommended() {
        assertEquals(1, ModelCatalog.models.count { it.recommended })
        assertEquals("small-f16", ModelCatalog.recommended.id)
    }

    @Test
    fun live_capability_follows_the_xrt_hint_and_only_the_near_real_time_models_qualify() {
        // liveCapable == xRT <= LIVE_XRT_MAX, evaluated per spec.
        for (m in ModelCatalog.models) {
            assertEquals("liveCapable disagrees with xRT for ${m.id}", m.xRT <= ModelSpec.LIVE_XRT_MAX, m.liveCapable)
        }
        val live = ModelCatalog.models.filter { it.liveCapable }.map { it.id }.toSet()
        // From the FP6 bench (dotprod-ON): only tiny and base-f16 keep up with speech.
        assertEquals(setOf("tiny-q5_1", "base-f16"), live)
        // The recommended default is deliberately NOT live-capable — hence the honest degrade.
        assertFalse("small-f16 is the quality pick, not the live pick", ModelCatalog.recommended.liveCapable)
    }

    @Test
    fun ids_and_file_names_are_unique() {
        assertEquals(ModelCatalog.models.size, ModelCatalog.models.map { it.id }.toSet().size)
        assertEquals(ModelCatalog.models.size, ModelCatalog.models.map { it.fileName }.toSet().size)
    }

    @Test
    fun lookup_helpers_resolve_and_reject_as_expected() {
        assertEquals("small-f16", ModelCatalog.byId("small-f16")?.id)
        assertEquals(null, ModelCatalog.byId("nope"))
        assertEquals(null, ModelCatalog.byId(null))
        assertEquals("base-f16", ModelCatalog.byFileName("ggml-base.bin")?.id)
    }
}
