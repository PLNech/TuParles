package pl.nech.tuparles.core

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The #42 priority rule made deterministic: committed decodes wait their turn, live
 * partials skip when the engine is busy. Uses suspending latches to pin the gate open
 * so the "busy" moment is exact, not timing-dependent.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DecodeGateTest {

    @Test
    fun partial_runs_and_returns_its_result_when_the_gate_is_free() = runTest {
        val gate = DecodeGate()
        assertEquals("ok", gate.partial { "ok" })
    }

    @Test
    fun partial_skips_with_null_while_a_committed_decode_holds_the_gate() = runTest {
        val gate = DecodeGate()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var committedResult = ""

        val committed = backgroundScope.launch {
            committedResult = gate.committed {
                entered.complete(Unit) // gate acquired
                release.await() // hold it open
                "committed-done"
            }
        }
        entered.await()

        // Engine busy: the partial must skip, not queue behind the committed decode.
        assertNull(gate.partial { "should-not-run" })

        release.complete(Unit)
        committed.join()
        assertEquals("committed-done", committedResult)

        // Free again: partials resume.
        assertEquals("after", gate.partial { "after" })
    }

    @Test
    fun committed_decodes_run_one_at_a_time_and_wait_their_turn() = runTest {
        val gate = DecodeGate()
        val order = mutableListOf<String>()
        val entered1 = CompletableDeferred<Unit>()
        val release1 = CompletableDeferred<Unit>()

        val first = backgroundScope.launch {
            gate.committed {
                entered1.complete(Unit)
                release1.await()
                order.add("first")
            }
        }
        entered1.await()

        val second = backgroundScope.launch { gate.committed { order.add("second") } }
        runCurrent() // give the second decode a chance to (fail to) acquire the gate

        assertTrue("second must not run while first holds the gate", order.isEmpty())

        release1.complete(Unit)
        first.join()
        second.join()
        assertEquals(listOf("first", "second"), order)
    }

    @Test
    fun a_partial_that_ran_frees_the_gate_for_the_next_decode() = runTest {
        val gate = DecodeGate()
        assertEquals(1, gate.partial { 1 })
        // If the previous partial had leaked the lock, a committed decode would deadlock here.
        var ran = false
        gate.committed { ran = true }
        assertTrue(ran)
    }
}
