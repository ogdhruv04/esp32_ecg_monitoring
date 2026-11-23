package com.dhruv.ecgmonitor

import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/**
 * The heart rate the main, recording and guided-breathing screens show
 * (EcgPipeline.heartRate, LiveHeartRate.kt), replayed through the pipeline
 * exactly as BLE feeds it and checked at every quality assessment (4 Hz) where
 * the gate says GOOD, which is when the screens show it.
 *
 * The yardstick is independent of the streaming detector: R peaks found
 * offline by NeuroKit2 on the zero-phase-filtered capture
 * (make_live_hr_fixtures.py, analysis/app_live_hr_reference.txt).
 *  - Where the reference window is clean, the live rate must be shown and be
 *    within 5 bpm of it.
 *  - Wherever the live rate is shown, it must be within 5 bpm of the reference,
 *    or of the loose reference where one ectopic or missed beat leaves the
 *    strict one undefined. A rate shown with no reference at all fails.
 *
 * Not against the session's heart rate: that is one median over minutes, and
 * the real rate leaves it. tb02 rises to 94.8 bpm at 156.75 s against a 77 bpm
 * session and dual03 falls to 94.8 bpm at 32.5 s against 103 (both from the
 * independent reference). Those departures are counted and written to
 * analysis/app_live_hr.txt.
 *
 * The old display (BeatDetector.heartRate) is run through the same check and
 * must fail it on tb02: that is the bug seen on the phone (27 and 101 bpm on
 * GOOD), and it shows this test catches it.
 */
class LiveHeartRateTest {

    private class Ref(val strict: Double?, val loose: Double?)

    private fun reference(name: String): Map<Long, Ref> =
        javaClass.getResourceAsStream("/livehr/${name}_reference.tsv")!!.bufferedReader().readLines().drop(1).associate {
            val f = it.split('\t')
            fun d(i: Int) = f.getOrNull(i)?.takeIf { s -> s.isNotEmpty() }?.toDouble()
            Math.round(f[0].toDouble() * 4) to Ref(d(1), d(2))
        }

    class Outcome(
        val good: Int, val strictMoments: Int, val strictShown: Int, val shown: Int,
        val failures: List<String>, val oldFailures: Int, val sessionHr: Double,
        val offSession: List<String>, val curvePoints: Int, val curveFar: Int,
    )

    private fun run(name: String, file: String): Outcome {
        val ref = reference(name)
        val packets = SessionReplay.capturePackets(file)
        // The pipeline's sample count starts at the first packet; the
        // reference's clock at the first sample of the capture.
        val origin = packets.first().sampleOffset
        val p = EcgPipeline()
        val beats = ArrayList<LocatedBeat>()
        p.detector.onLocated.let { prev -> p.detector.onLocated = { prev?.invoke(it); beats += it } }

        var lastAssess = -1L
        var good = 0; var strictMoments = 0; var strictShown = 0; var shown = 0; var oldFailures = 0
        var curvePoints = 0; var curveFar = 0
        var firstGood = -1L
        val failures = ArrayList<String>()
        val moments = ArrayList<Triple<Double, Double, Ref>>()   // (t, live, reference) where shown
        for (pk in packets) {
            p.onPacket(pk.packet)
            val n = p.detector.sampleCount
            if (n / EcgPipeline.QUALITY_EVERY == lastAssess) continue
            lastAssess = n / EcgPipeline.QUALITY_EVERY
            if (!p.qualityReady || p.signalQuality.level != SignalQuality.Level.GOOD) continue
            if (firstGood < 0) firstGood = n
            good++
            val t = (n + origin) / EcgFilter.ECG_SAMPLE_RATE
            val r = ref[Math.round(t * 4)] ?: Ref(null, null)
            val live = p.heartRate
            val old = p.detector.heartRate
            if (r.strict != null) {
                strictMoments++
                if (live != null) strictShown++
                if (old != null && abs(old - r.strict) > 5) oldFailures++
                // Guided breathing's beat-to-beat curve over the same 10 s.
                val s = p.live.snapshot()
                for ((bt, bpm) in s.curve) if (bt > s.t1 - LiveHeartRate.WINDOW_S && bpm.isFinite()) {
                    curvePoints++
                    if (abs(bpm - r.strict) > 0.2 * r.strict) curveFar++
                }
            }
            if (live == null) continue
            shown++
            moments += Triple(t, live, r)
            val yard = r.strict ?: r.loose
            if (yard == null || abs(live - yard) > 5.0)
                failures += "t=%.2f s live %.1f bpm, reference %s".format(t, live, yard?.let { "%.1f".format(it) } ?: "none")
        }
        val sessionHr = SessionMeasures.heartRate(beats.filter { it.pos >= firstGood }, EcgFilter.ECG_SAMPLE_RATE).value!!
        val offSession = moments.filter { abs(it.second - sessionHr) > 5 }.map { (t, live, r) ->
            "t=%.2f s live %.1f, reference %s".format(t, live, (r.strict ?: r.loose)?.let { "%.1f".format(it) } ?: "none")
        }
        return Outcome(good, strictMoments, strictShown, shown, failures, oldFailures, sessionHr, offSession, curvePoints, curveFar)
    }

    private fun check(name: String, file: String, oldMustFail: Boolean): Outcome {
        val o = run(name, file)
        println("$name: GOOD at ${o.good} moments; shown at ${o.shown}; clean reference at ${o.strictMoments}, shown at " +
            "${o.strictShown}; failures ${o.failures.size}; old display failures ${o.oldFailures}; session HR " +
            "%.2f, live more than 5 bpm off it at ${o.offSession.size} moments; curve ${o.curveFar}/${o.curvePoints} points >20%% off".format(o.sessionHr))
        o.offSession.firstOrNull()?.let { println("  first off the session HR: $it; last: ${o.offSession.last()}") }
        assertTrue("$name: live rate wrong or unverifiable:\n" + o.failures.take(20).joinToString("\n"), o.failures.isEmpty())
        assertTrue("$name: live rate hidden too often where the reference is clean (${o.strictShown}/${o.strictMoments})",
            o.strictShown >= 0.95 * o.strictMoments)
        assertTrue("$name: vacuous, no clean reference while GOOD", o.strictMoments > 100)
        assertTrue("$name: guided-breathing curve far from the reference (${o.curveFar}/${o.curvePoints})",
            o.curveFar <= 0.05 * o.curvePoints)
        if (oldMustFail) assertTrue("$name: the old display passes, so this test would not catch the bug", o.oldFailures > 0)
        return o
    }

    @Test fun testBoard02() { check("tb02", "20261027_174352_testboard02.csv", oldMustFail = true) }

    @Test fun dual03() { check("dual03_ring", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv", oldMustFail = false) }
}
