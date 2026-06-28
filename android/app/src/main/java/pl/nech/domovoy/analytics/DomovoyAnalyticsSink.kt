package pl.nech.domovoy.analytics

fun interface DomovoyAnalyticsSink {
    /** Return true once events have been accepted by the app transport/outbox. */
    fun send(events: List<DomovoyAnalyticsEvent>): Boolean
}
