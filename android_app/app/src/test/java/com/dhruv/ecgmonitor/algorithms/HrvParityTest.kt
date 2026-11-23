package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.algorithms.Fixtures.assertSame
import com.dhruv.ecgmonitor.algorithms.Fixtures.close
import com.dhruv.ecgmonitor.algorithms.Fixtures.num
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Each HRV port against algorithms/ on NN series from real recordings
 * (make_session_fixtures.py): the gated Result of every measure (value or the
 * exact withheld reason, counts, valid time, coverage), and the ungated
 * arithmetic, so a measure our short recordings rightly withhold is still
 * checked number for number. "stitched" joins the accepted intervals of three
 * recordings so that every gate passes.
 */
class HrvParityTest {

    private fun series(name: String): NnSeries {
        val rows = Fixtures.resource("session/nn_$name.csv").lines().drop(1).filter { it.isNotBlank() }
        val t = DoubleArray(rows.size) { num(rows[it].split(',')[0]) }
        val nn = DoubleArray(rows.size - 1) { num(rows[it + 1].split(',')[1]) }
        return NnSeries(t, nn)
    }

    private fun check(name: String) {
        val nn = series(name)
        val got = Hrv.all(nn)
        val expected = Fixtures.results("session/nn_${name}_expected.tsv")
        assertEquals("$name: measures", expected.map { it.key }.toSet(), got.keys)
        for (e in expected) assertSame("$name ${e.key}", e, got.getValue(e.key))

        // The arithmetic without the gates.
        val raw = Fixtures.resource("session/nn_${name}_raw.tsv").lines().filter { it.isNotBlank() }
            .associate { it.split('\t').let { c -> c[0] to num(c[1]) } }
        val (a, b) = nn.pairs()
        val v = nn.values; val t = nn.times
        val runs = nn.runs(AlgConfig.DFA_SCALE_MAX)
        val kotlin = mapOf(
            "rmssd" to if (a.isNotEmpty()) Hrv.rmssdRaw(a, b) else Double.NaN,
            "pnn50" to if (a.isNotEmpty()) Hrv.pnn50Raw(a, b) else Double.NaN,
            "sdnn" to if (v.size > 1) stdDdof1(v) else Double.NaN,
            "sd1" to if (a.size > 1) Hrv.sdRaw(a, b, sum = false) else Double.NaN,
            "sd2" to if (a.size > 1) Hrv.sdRaw(a, b, sum = true) else Double.NaN,
            "lf" to if (v.size > 2) Hrv.bandPower(t, v, AlgConfig.LF_BAND) else Double.NaN,
            "hf" to if (v.size > 2) Hrv.bandPower(t, v, AlgConfig.HF_BAND) else Double.NaN,
            "dfa_alpha1" to if (runs.isNotEmpty()) Hrv.dfaAlpha1Raw(runs) else Double.NaN,
            "sampen" to nn.runs(AlgConfig.SAMPEN_M + 1).let { r ->
                if (r.isNotEmpty() && v.size > 1) Hrv.sampleEntropyRaw(r, stdDdof1(v)) else Double.NaN
            },
        )
        assertEquals("$name: raw measures", raw.keys, kotlin.keys)
        for ((k, x) in raw) close("$name raw $k", x, kotlin.getValue(k))
        println("$name: ${got.values.count { it.ok }}/${got.size} shown; raw ${raw.count { !it.value.isNaN() }} values match")
    }

    @Test fun chest() = check("chest")
    @Test fun finger() = check("finger")
    @Test fun artifactAndGaps() = check("artifact_gaps")
    @Test fun polarityFlip() = check("polarity_flip")
    @Test fun testBoard01() = check("tb01")
    @Test fun testBoard02() = check("tb02")
    /** Every gate passes here, so every gated value path runs. */
    @Test fun stitched() {
        check("stitched")
        assertEquals("every measure shown", 10, Hrv.all(series("stitched")).values.count { it.ok })
    }
}
