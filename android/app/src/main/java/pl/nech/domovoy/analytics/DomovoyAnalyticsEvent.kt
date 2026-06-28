package pl.nech.domovoy.analytics

/** Local-first app telemetry event. Values are intentionally structured and bounded. */
data class DomovoyAnalyticsEvent(
    val observedAtMillis: Long,
    val name: String,
    val category: String = "app",
    val severity: String = "info",
    val sessionId: String,
    val runId: String,
    val attributes: Map<String, String> = emptyMap(),
)
