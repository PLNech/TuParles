package pl.nech.tuparles.core

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Serializes access to the non-thread-safe native whisper singleton so exactly one
 * decode touches it at a time, with the priority rule of issue #42:
 *
 *  - **committed** decodes (post-hoc, a saved note's transcript) *wait* their turn —
 *    they are the durable product and must always complete.
 *  - **partial** decodes (the live tail-window preview) *try and skip*: if the engine
 *    is busy right now they return null rather than queue, so a slow device produces
 *    fewer partials, never a backlog, and never delays a committed decode.
 *
 * Kept as its own tiny unit (not inlined in the engine) so the priority behaviour is
 * unit-testable on the JVM without the native library or an Android Context.
 */
class DecodeGate {
    private val mutex = Mutex()

    /** A committed decode: acquires the gate, waiting if a decode is in flight. */
    suspend fun <T> committed(block: suspend () -> T): T = mutex.withLock { block() }

    /**
     * A partial decode: runs [block] only if the gate is free at this instant, else
     * returns null (skip this window). Never waits, never queues behind a committed decode.
     */
    suspend fun <T> partial(block: suspend () -> T): T? {
        if (!mutex.tryLock()) return null
        return try {
            block()
        } finally {
            mutex.unlock()
        }
    }
}
