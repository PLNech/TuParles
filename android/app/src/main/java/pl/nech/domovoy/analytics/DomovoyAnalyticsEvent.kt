package pl.nech.domovoy.analytics

/**
 * Local-first app telemetry event. Values are intentionally structured and bounded.
 * Attribute values are typed primitives (Int/Long/Double/Float/Boolean/String) so
 * they serialize to native JSON types for downstream duckdb / data-lake / NLP use;
 * the String `event()` path simply stores Strings here.
 */
data class DomovoyAnalyticsEvent(
    val observedAtMillis: Long,
    val name: String,
    val category: String = "app",
    val severity: String = "info",
    val sessionId: String,
    val runId: String,
    val attributes: Map<String, Any?> = emptyMap(),
)
