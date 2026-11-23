package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.BeatDetector
import com.dhruv.ecgmonitor.SessionKind
import com.dhruv.ecgmonitor.SessionMeasures
import com.dhruv.ecgmonitor.SessionRecorder
import com.dhruv.ecgmonitor.algorithms.Fixtures.assertSame
import com.dhruv.ecgmonitor.algorithms.Fixtures.close
import com.dhruv.ecgmonitor.algorithms.Fixtures.num
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The whole Session report against session_reference.py: real recordings fed
 * sample by sample through BeatDetector and SessionRecorder in the order
 * EcgPipeline uses, then every measure (heart rate, breathing rate and the
 * HRV set) and the fused breathing rate of every 32 s window compared.
 * This is the breathing port's parity test as well: its per-window results
 * need the detector's beats and the filtered signal together.
 */
class SessionParityTest {

    private class Case(val input: String, val s0: Long, val s1: Long, val kind: SessionKind)

    private val cases: Map<String, Case> = Fixtures.resource("session/session_cases.tsv").lines().drop(1)
        .filter { it.isNotBlank() }.associate { it.split('\t').let { c -> c[0] to Case(c[1], c[2].toLong(), c[3].toLong(), SessionKind.valueOf(c[4].uppercase())) } }

    private fun record(case: Case): SessionRecorder {
        val rows = Fixtures.resource(case.input).lines().drop(1).filter { it.isNotBlank() }.map { it.split(',') }
        val d = BeatDetector()
        var rec: SessionRecorder? = null
        d.onLocated = { rec?.onBeat(it) }
        for (r in rows) {
            val skip = r[1].toInt()
            if (skip > 0) {
                d.skip(skip)
                rec?.onSkip(skip)
                if (rec?.finished == true) break
            }
            // The session starts where the app would start it: on the sample
            // whose absolute index is s0.
            if (rec == null && d.sampleCount >= case.s0) {
                assertEquals("session must start on a sample boundary", case.s0, d.sampleCount)
                rec = SessionRecorder(case.s0, case.s1)
            }
            val v = r[0].toFloat()
            rec?.onSample(v)
            d.process(v)
            if (rec?.checkEnd() == true) break
            rec?.let { assertEquals("recorder and detector disagree on the clock", it.index, d.sampleCount) }
        }
        assertTrue("input ended before the session did", rec?.finished == true)
        return rec!!
    }

    private fun check(name: String) {
        val case = cases.getValue(name)
        val m = record(case).report(case.kind)
        val expected = Fixtures.results("session/session_${name}_expected.tsv")
        assertEquals("$name: report keys", expected.map { it.key }, SessionMeasures.keys(case.kind))
        for (e in expected) assertSame("$name ${e.key}", e, m.results.getValue(e.key))

        val windows = Fixtures.resource("session/session_${name}_windows.tsv").lines().drop(1).filter { it.isNotBlank() }
            .map { it.split('\t') }
        assertEquals("$name: breathing windows", windows.size, m.windows.size)
        for ((k, w) in windows.withIndex()) {
            val (w0, r) = m.windows[k]
            close("$name window $k start", num(w[0]), w0)
            val label = "$name window $k (${w[0]} s)"
            if (w[1] == "nan") {
                assertEquals("$label: phone gives ${r.value}", null, r.value)
                assertEquals("$label reason", w[2], r.withheld)
            } else close("$label rate", num(w[1]), r.value ?: Double.NaN)
            assertEquals("$label n_used", w[3].toInt(), r.nUsed)
            close("$label coverage", num(w[4]), r.coverage)
        }
        println("$name: ${m.beats} beats, ${m.results.values.count { it.ok }}/${m.results.size} shown, " +
                "${m.windows.count { it.second.ok }}/${m.windows.size} breathing windows with a rate")
    }

    @Test fun finger() = check("finger")
    @Test fun chest() = check("chest")
    @Test fun artifactAndGaps() = check("artifact_gaps")
    /** Full 3-minute sessions on the test board, with real lost samples. */
    @Test fun testBoard01() = check("tb01")
    @Test fun testBoard02() = check("tb02")
    /** The extended report: DFA alpha1 and sample entropy as well. */
    @Test fun testBoard02Extended() = check("tb02_ext")
}
