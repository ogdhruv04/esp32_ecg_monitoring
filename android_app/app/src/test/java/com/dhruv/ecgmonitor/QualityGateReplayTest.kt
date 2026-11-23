package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Locale

/**
 * The quality gate on our own recordings, through EcgPipeline exactly as BLE
 * feeds it: the verdict at every assessment, with the artifact check (sqi2)
 * and as it was without it (kurtosis and band share alone, recomputed from
 * the same assessment). Writes build/reports/quality_gate_replay.txt, which is
 * kept as analysis/app_quality_gate_replay.txt.
 *
 * What it requires: tb02's electrode-settling transients (first 42 s; beats
 * are clean from 44 s on, analysis/app_live_hr.txt) are no longer GOOD, and
 * the clean stretches (tb02 after 45 s, dual03) lose nothing.
 */
class QualityGateReplayTest {
    private class Counts { val now = IntArray(3); val before = IntArray(3); var artifact = 0
        val n get() = now.sum() }

    private fun run(file: String, split: (Double) -> Int, parts: Int): Array<Counts> {
        val packets = SessionReplay.capturePackets(file)
        val origin = packets.first().sampleOffset
        val p = EcgPipeline()
        val out = Array(parts) { Counts() }
        var last: SignalQuality.Result? = null
        for (pk in packets) {
            p.onPacket(pk.packet)
            val r = p.signalQuality
            if (r === last) continue
            last = r
            if (!p.qualityReady) continue
            val t = (pk.sampleOffset - origin + pk.packet.count) / EcgFilter.ECG_SAMPLE_RATE
            val k = split(t)
            if (k < 0) continue
            out[k].now[r.level.ordinal]++
            out[k].before[SignalQuality.levelWithoutArtifactCheck(r.kSqi, r.pSqi).ordinal]++
            if (r.artifact) out[k].artifact++
        }
        return out
    }

    private fun shares(c: IntArray): String {
        val n = c.sum().coerceAtLeast(1)
        return String.format(Locale.UK, "GOOD %5.1f%%  FAIR %5.1f%%  POOR %5.1f%%", 100.0 * c[0] / n, 100.0 * c[1] / n, 100.0 * c[2] / n)
    }

    @Test fun ownRecordings() {
        val report = StringBuilder()
        report.appendLine("# QualityGateReplayTest: gate ${SignalQuality.VERSION} on our own recordings through EcgPipeline (the app's own filter,")
        report.appendLine("# baseline remover and detector), one line per verdict the pipeline produced (about 4 a second).")
        report.appendLine("# before = kurtosis and band share alone; now = with the artifact check. No rhythm or quality reference exists;")
        report.appendLine("# tb02's first 42 s are known electrode-settling transients (analysis/app_live_hr.txt).")
        report.appendLine()
        fun line(name: String, c: Counts) {
            report.appendLine(String.format(Locale.UK, "%-22s %5d verdicts | before: %s | now: %s | artifact at %d",
                name, c.n, shares(c.before), shares(c.now), c.artifact))
        }
        val tb02 = run("20261027_174352_testboard02.csv", { t -> if (t <= 42) 0 else if (t > 45) 1 else -1 }, 2)
        line("tb02, first 42 s", tb02[0]); line("tb02, after 45 s", tb02[1])
        val whole: (Double) -> Int = { 0 }
        val rest = listOf(
            "tb01" to "20261027_173714_testboard01.csv",
            "dual03 chest" to "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv",
            "dual03 finger" to "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv",
            "dual01 chest (failed)" to "20260929_153252_dual01_c3chest_wroomfinger_ring.csv",
            "dual01 finger (failed)" to "20260929_153252_dual01_c3chest_wroomfinger_ref.csv",
            "dual02 chest (failed)" to "20260929_155511_dual02_rbias_c3chest_wroomfinger_ring.csv",
            "dual02 finger" to "20260929_155511_dual02_rbias_c3chest_wroomfinger_ref.csv",
        ).associate { (name, file) -> name to run(file, whole, 1)[0].also { line(name, it) } }
        File("build/reports").mkdirs()
        File("build/reports/quality_gate_replay.txt").writeText(report.toString())
        print(report)

        val settling = tb02[0]
        assertTrue("vacuous: the old gate called few settling verdicts GOOD (${settling.before[0]})", settling.before[0] > 40)
        assertTrue("settling transients still GOOD at ${settling.now[0]} of ${settling.before[0]} verdicts",
            settling.now[0] <= settling.before[0] / 5)
        assertEquals("tb02 after 45 s lost GOOD verdicts", tb02[1].before[0], tb02[1].now[0])
        for (name in listOf("dual03 chest", "dual03 finger")) {
            assertEquals("$name lost GOOD verdicts", rest.getValue(name).before[0], rest.getValue(name).now[0])
        }
    }
}
