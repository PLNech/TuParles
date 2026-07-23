package pl.nech.tuparles.model

import java.net.URI

/**
 * Pure redirect resolution for the direct-HTTP download fallback. The Hugging Face
 * `resolve/main/<file>` URL answers with a 302 to a CDN host; `HttpURLConnection`
 * follows *same-protocol* redirects on its own, but we follow manually so the decision
 * is explicit, testable, and can enforce the one rule that matters here:
 * **never downgrade to plain http.** No network, no Android — just string/URI logic.
 */
object HttpRedirect {

    /** How many hops we will follow before giving up (a redirect loop guard). */
    const val MAX_REDIRECTS = 5

    /** HTTP status codes we treat as "follow the Location header". */
    fun isRedirect(status: Int): Boolean = status in 300..399 && status != 304

    /**
     * Resolve [location] (absolute or relative) against [currentUrl] into the next URL to
     * fetch. Throws for a missing Location or an insecure (non-https) target — we refuse
     * to be redirected off TLS. HF → CDN stays https→https, so this only ever fires on a
     * genuinely hostile/misconfigured hop.
     */
    fun resolve(currentUrl: String, location: String?): String {
        require(!location.isNullOrBlank()) { "redirect without a Location header" }
        val next = URI(currentUrl).resolve(location).toString()
        require(next.startsWith("https://")) { "refusing insecure redirect: $currentUrl -> $next" }
        return next
    }
}
