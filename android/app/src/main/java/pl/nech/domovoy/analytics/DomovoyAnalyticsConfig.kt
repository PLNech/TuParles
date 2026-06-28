package pl.nech.domovoy.analytics

data class DomovoyAnalyticsConfig(
    val enabled: Boolean = true,
    val devMode: Boolean = false,
    val maxQueuedEvents: Int = 2_000,
    val includeStackTrace: Boolean = false,
    val appVersion: String = "unknown",
)
