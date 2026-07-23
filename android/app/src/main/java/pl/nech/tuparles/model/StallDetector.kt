package pl.nech.tuparles.model

/**
 * A pure, clock-injected watchdog over a download's byte progress. It answers one
 * question — "has this download made no forward progress for too long?" — so the
 * coordinator can give up on a stalled transfer and fall back to another path.
 *
 * Why it exists: on a Fairphone 6 / Android 15 the system `DownloadManager`'s
 * JobScheduler job was observed sitting RUNNABLE with every constraint satisfied yet
 * never promoted to active — 0 bytes, indefinitely (scheduler deferral, not policy;
 * `cmd jobscheduler run -f` unstuck it instantly). See
 * `docs/research/2026-07-23-android-lean-apk-design.md`. This detector turns that
 * "runnable forever" symptom into a bounded wait.
 *
 * No Android, no wall clock of its own: the time source is injected, so the whole thing
 * is exercised in JVM tests with a fake clock rather than a real sleep.
 *
 * @param stallThresholdMs how long with zero forward progress counts as stalled.
 * @param now monotonic-ish time source in milliseconds (e.g. `System::currentTimeMillis`).
 */
class StallDetector(
    private val stallThresholdMs: Long,
    private val now: () -> Long,
) {
    private var started = false
    private var lastBytes = 0L
    private var lastProgressAt = 0L

    /**
     * Feed the current byte count on each poll. Returns true once the download has made
     * no forward progress (bytes never increased) for at least [stallThresholdMs].
     * Any forward movement resets the clock, so a transfer that is genuinely trickling
     * bytes is never declared stalled.
     */
    fun isStalled(bytesSoFar: Long): Boolean {
        val t = now()
        if (!started) {
            started = true
            lastBytes = bytesSoFar
            lastProgressAt = t
            return false
        }
        if (bytesSoFar > lastBytes) {
            lastBytes = bytesSoFar
            lastProgressAt = t
        }
        return t - lastProgressAt >= stallThresholdMs
    }
}
