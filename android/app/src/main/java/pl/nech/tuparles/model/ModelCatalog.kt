package pl.nech.tuparles.model

/**
 * One downloadable on-device whisper model. Pure data — no Android, no I/O — so the
 * catalog is trivially editable and unit-testable, and so a follow-up bench (the
 * dotprod A/B, see docs/research/2026-07-22-android-model-bench.md) can revise the
 * lineup by editing [ModelCatalog.models] alone.
 *
 * @param id        stable machine key (persisted as the active-model selection).
 * @param fileName  the GGML file name on Hugging Face; also the on-disk file name.
 * @param label     French-flavoured user-facing name.
 * @param character honest one-line description of the speed/quality trade-off.
 * @param sizeBytes exact download size, for the "you are about to pull N MB" prompt
 *                  and for a cheap integrity pre-check before the (slower) sha256.
 * @param sha256    lower-case hex digest, verified before a download is ever activated.
 * @param recommended exactly one entry is the recommended default (see the bench).
 */
data class ModelSpec(
    val id: String,
    val fileName: String,
    val label: String,
    val character: String,
    val sizeBytes: Long,
    val sha256: String,
    val recommended: Boolean = false,
) {
    /** The whisper.cpp GGML mirror; resolve endpoint streams the actual weights. */
    val url: String get() = "$HF_BASE$fileName"

    /** Whole megabytes, for compact UI (e.g. "466 Mo"). */
    val sizeMb: Int get() = ((sizeBytes + BYTES_PER_MB / 2) / BYTES_PER_MB).toInt()

    private companion object {
        const val HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
        const val BYTES_PER_MB = 1024L * 1024L
    }
}

/**
 * The download-picker lineup, dropping the dotprod-dominated q5 rungs the bench flagged.
 * Sizes are exact bytes; sha256 digests are the git-LFS pointer `oid`s from the mirror
 * (four cross-checked against local files during the build). Ordered fastest→most-accurate
 * so a list renders as a natural speed↔quality ladder.
 */
object ModelCatalog {

    /** Bundled dev asset (see [ModelSpec.fileName] "base"): only present in a dev build. */
    const val BUNDLED_ASSET_PATH = "models/ggml-base.bin"
    const val BUNDLED_ASSET_NAME = "ggml-base"

    val models: List<ModelSpec> = listOf(
        ModelSpec(
            id = "tiny-q5_1",
            fileName = "ggml-tiny-q5_1.bin",
            label = "Tiny",
            character = "le plus rapide, le plus brouillon",
            sizeBytes = 32_152_673L,
            sha256 = "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7",
        ),
        ModelSpec(
            id = "base-f16",
            fileName = "ggml-base.bin",
            label = "Base",
            character = "léger, quasi temps réel, bute sur le vocabulaire technique",
            sizeBytes = 147_951_465L,
            sha256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
        ),
        ModelSpec(
            id = "small-f16",
            fileName = "ggml-small.bin",
            label = "Small",
            character = "le meilleur équilibre (~3.4x temps réel)",
            sizeBytes = 487_601_967L,
            sha256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
            recommended = true,
        ),
        ModelSpec(
            id = "medium-q5_0",
            fileName = "ggml-medium-q5_0.bin",
            label = "Medium",
            character = "le plus précis, lent (~18x) — pour le différé",
            sizeBytes = 539_212_467L,
            sha256 = "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
        ),
        ModelSpec(
            id = "large-v3-turbo-q5_0",
            fileName = "ggml-large-v3-turbo-q5_0.bin",
            label = "Large v3 turbo",
            character = "quasi parfait, le plus lent",
            sizeBytes = 574_041_195L,
            sha256 = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        ),
    )

    /** The house default the download card offers first (bench-picked). */
    val recommended: ModelSpec get() = models.first { it.recommended }

    fun byId(id: String?): ModelSpec? = id?.let { key -> models.firstOrNull { it.id == key } }

    fun byFileName(name: String): ModelSpec? = models.firstOrNull { it.fileName == name }
}
