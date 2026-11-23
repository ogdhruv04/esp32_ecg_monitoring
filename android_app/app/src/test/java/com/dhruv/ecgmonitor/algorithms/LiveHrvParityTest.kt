package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.BeatDetector
import com.dhruv.ecgmonitor.LiveHrv
import com.dhruv.ecgmonitor.algorithms.Fixtures.close
import com.dhruv.ecgmonitor.algorithms.Fixtures.num
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The guided-breathing screen's live numbers against
 * session_reference.live_window: the test-board recordings fed sample by
 * sample through BeatDetector and LiveHrv, and at fixed points the RMSSD of
 * the last 90 s and the fused breathing rate of the last 32 s compared, value
 * or withheld reason.
 */
class LiveHrvParityTest {
    private class Row(val n: Long, val key: String, val value: Double, val withheld: String, val nUsed: Int, val coverage: Double)

    private fun check(name: String) {
        val rows = Fixtures.resource("session/live_cases.tsv").lines().drop(1).filter { it.isNotBlank() }
            .map { it.split('\t') }.filter { it[0] == name }
            .map { Row(it[1].toLong(), it[2], num(it[3]), it[4], it[5].toInt(), num(it[8])) }
        assertTrue("$name: no live cases", rows.size >= 6)
        val points = rows.map { it.n }.distinct().sorted()
        val input = Fixtures.resource("session/${name}_input.csv").lines().drop(1).filter { it.isNotBlank() }.map { it.split(',') }
        val d = BeatDetector(); val live = LiveHrv()
        d.onLocated = { live.onBeat(it) }
        var shown = 0; var k = 0
        for (r in input) {
            if (k == points.size) break
            val skip = r[1].toInt()
            if (skip > 0) { d.skip(skip); live.onSkip(skip) }
            val v = r[0].toFloat()
            live.onSample(v); d.process(v)
            assertEquals(d.sampleCount, live.index)
            if (live.index == points[k]) {
                val snap = live.snapshot()
                for (e in rows.filter { it.n == points[k] }) {
                    val got = if (e.key == "rmssd") snap.rmssd else snap.breathing
                    val label = "$name at ${e.n / 256} s ${e.key}"
                    if (e.value.isNaN()) {
                        assertEquals("$label: phone shows ${got.value}", null, got.value)
                        assertEquals("$label reason", e.withheld, got.withheld)
                    } else { close("$label", e.value, got.value ?: Double.NaN); shown++ }
                    assertEquals("$label n_used", e.nUsed, got.nUsed)
                    close("$label coverage", e.coverage, got.coverage)
                }
                k++
            }
        }
        assertEquals("$name: every point reached", points.size, k)
        println("$name: ${points.size} points, $shown values shown")
    }

    @Test fun testBoard01() = check("tb01")
    @Test fun testBoard02() = check("tb02")
}
