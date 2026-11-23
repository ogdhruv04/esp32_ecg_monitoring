package com.dhruv.ecgmonitor

import com.dhruv.ecgmonitor.algorithms.AlgConfig
import com.dhruv.ecgmonitor.algorithms.Breathing
import com.dhruv.ecgmonitor.algorithms.Hrv
import com.dhruv.ecgmonitor.algorithms.NnSeries
import com.dhruv.ecgmonitor.algorithms.Result
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.floor

/** session_config.json "guided_breathing". AlgorithmsConfigTest checks it. */
object GuidedBreathingConfig {
    const val PACE_PER_MIN = 6.0
    const val INHALE_S = 5.0
    const val EXHALE_S = 5.0
    const val DURATION_S = 180.0
    const val RMSSD_WINDOW_S = 90.0
    const val CURVE_S = 60.0
}

/** Where the pacer is [elapsedS] into the exercise. [size] runs 0..1: up
 *  during the inhale, down during the exhale, eased so it starts and ends slowly. */
data class PacerPhase(val inhale: Boolean, val secondsLeftInPhase: Double, val size: Double, val breath: Int)

fun pacer(elapsedS: Double): PacerPhase {
    val cycle = GuidedBreathingConfig.INHALE_S + GuidedBreathingConfig.EXHALE_S
    val e = maxOf(elapsedS, 0.0)
    val breath = floor(e / cycle).toInt()
    val t = e - breath * cycle
    return if (t < GuidedBreathingConfig.INHALE_S) {
        val f = t / GuidedBreathingConfig.INHALE_S
        PacerPhase(true, GuidedBreathingConfig.INHALE_S - t, (1 - cos(PI * f)) / 2, breath)
    } else {
        val f = (t - GuidedBreathingConfig.INHALE_S) / GuidedBreathingConfig.EXHALE_S
        PacerPhase(false, cycle - t, (1 + cos(PI * f)) / 2, breath)
    }
}

/** The live numbers at one moment. [curve]: (beat time s, bpm) of every
 *  accepted NN interval of the last CURVE_S, NaN bpm at a hole. */
class LiveSnapshot(val t1: Double, val rmssd: Result, val breathing: Result, val curve: List<Pair<Double, Double>>)

/**
 * Sliding windows over the live stream for the guided-breathing screen. Keeps
 * the last KEEP_S of filtered samples (NaN where lost) and located beats;
 * [snapshot] applies the ported measures to windows ending at the newest
 * sample. session_reference.live_window is the reference; LiveHrvParityTest
 * pins it. Fed by EcgPipeline in the same order as SessionRecorder.
 */
class LiveHrv(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {
    private val n = (KEEP_S * fs).toInt()
    private val y = FloatArray(n) { Float.NaN }
    private val beats = ArrayDeque<LocatedBeat>()
    /** Absolute index of the next sample. */
    var index = 0L; private set

    fun onSample(f: Float) { y[(index % n).toInt()] = f; index++; trim() }

    fun onSkip(k: Int) {
        for (i in 0 until minOf(k, n)) y[((index + i) % n).toInt()] = Float.NaN
        index += k
        trim()
    }

    fun onBeat(b: LocatedBeat) { beats.addLast(b) }

    private fun trim() {
        while (beats.isNotEmpty() && beats.first().pos < index - n) beats.removeFirst()
    }

    private fun beatsIn(t0: Double, t1: Double) = beats.filter { it.pos / fs >= t0 && it.pos / fs < t1 }

    fun snapshot(): LiveSnapshot {
        val t1 = index / fs
        val nn = NnSeries.fromBeats(beatsIn(t1 - GuidedBreathingConfig.RMSSD_WINDOW_S, t1), fs)
        val w = AlgConfig.BR_WINDOW_S
        val len = (w * fs).toInt()
        val y0 = index - len
        val win = FloatArray(len) { i -> val a = y0 + i; if (a < 0) Float.NaN else y[(a % n).toInt()] }
        val mods = Breathing.modulations(win, y0, beatsIn(t1 - w, t1), fs)
        val br = Breathing.rate(mods, t1 - w, t1).getValue("fused")
        val curveNn = NnSeries.fromBeats(beatsIn(t1 - GuidedBreathingConfig.CURVE_S, t1), fs)
        val curve = curveNn.nnMs.indices.map { i ->
            val ms = curveNn.nnMs[i]
            curveNn.beatT[i + 1] to (if (ms.isFinite()) 60000.0 / ms else Double.NaN)
        }
        return LiveSnapshot(t1, Hrv.rmssd(nn), br, curve)
    }

    companion object {
        /** Long enough for the RMSSD window, with margin. */
        const val KEEP_S = 96.0
    }
}
