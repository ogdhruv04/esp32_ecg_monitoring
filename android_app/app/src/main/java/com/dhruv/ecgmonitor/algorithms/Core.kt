package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.BeatDetector
import com.dhruv.ecgmonitor.LocatedBeat
import java.math.BigDecimal
import java.math.RoundingMode

/*
 * Port of algorithms/core.py: the NN series, the result type and the
 * minimum-window gate. Every file in this package is a port of one module of
 * the Python algorithms/ package, which is the reference: HrvParityTest and
 * SessionParityTest require the same values (to 1e-9) and the same withheld
 * reasons, word for word, on fixtures from make_session_fixtures.py. If the
 * Python changes, regenerate the fixtures and change this to match.
 */

/** algorithms/config.json, version alg1, frozen 2026-11-11. AlgorithmsConfigTest
 *  fails if any value here differs from that file. */
object AlgConfig {
    const val VERSION = "alg1"
    val LF_BAND = doubleArrayOf(0.04, 0.15)
    val HF_BAND = doubleArrayOf(0.15, 0.40)
    const val LOMB_OVERSAMPLE = 8
    const val DFA_SCALE_MIN = 4
    const val DFA_SCALE_MAX = 16

    class MinWindow(
        val validS: Double, val nn: Int? = null, val pairs: Int? = null,
        val coverage: Double? = null, val nnInRuns: Int? = null,
    )

    val MIN_WINDOW: Map<String, MinWindow> = mapOf(
        "rmssd" to MinWindow(60.0, nn = 30, pairs = 5),
        "sdnn" to MinWindow(120.0, nn = 30),
        "pnn50" to MinWindow(60.0, nn = 30, pairs = 30),
        "hf" to MinWindow(60.0, nn = 30, coverage = 0.95),
        "lf" to MinWindow(120.0, nn = 30, coverage = 0.95),
        "sd1" to MinWindow(60.0, nn = 30, pairs = 5),
        "sd2" to MinWindow(120.0, nn = 30, pairs = 30),
        "dfa_alpha1" to MinWindow(120.0, nnInRuns = 200),
    )

    // Breathing (config.json "breathing"). Only the frozen choices are ported:
    // amp_mode peak_to_peak with flagged beats measured, fusion agree_or_ramp.
    const val BR_WINDOW_S = 32.0
    val BR_BAND_BPM = doubleArrayOf(4.0, 40.0)
    const val BR_LOMB_OVERSAMPLE = 8
    const val BR_MIN_BEATS = 16
    const val BR_MIN_BEAT_COVERAGE = 0.5
    const val BR_OUTLIER_MAD = 5.0
    const val BR_SHARE_HALFWIDTH_CYCLES = 1.0
    const val BR_PEAK_SHARE_MIN = 0.3
    const val BR_AMP_MODE = "peak_to_peak"
    const val BR_AMP_FLAGGED = true
    const val BR_FUSION = "agree_or_ramp"
    const val BR_AGREE_BPM = 3.0
    const val BR_RAMP_ALONE_SHARE = 0.4
}

/** algorithms.core.Result. [value] null = withheld, and [withheld] says why. */
data class Result(
    val name: String,
    val value: Double?,
    val unit: String,
    val withheld: String?,
    val nUsed: Int,
    val validS: Double,
    val spanS: Double,
    val coverage: Double,
    val extra: Map<String, Double> = emptyMap(),
) {
    val ok: Boolean get() = value != null
}

/** algorithms.core.NNSeries: one entry per inter-beat interval, NaN where the
 *  interval is not usable. [beatT] has one more entry than [nnMs]. */
class NnSeries(val beatT: DoubleArray, val nnMs: DoubleArray) {

    companion object {
        /** NNSeries.from_beats: pan_tompkins.rr_history (no depth limit), then clean_nn. */
        fun fromBeats(beats: List<LocatedBeat>, fs: Double): NnSeries {
            val t = DoubleArray(beats.size) { beats[it].pos / fs }
            return cleaned(t, rrHistory(beats, fs))
        }

        /** pan_tompkins.rr_history: an interval is NaN unless both beats are
         *  primary and unflagged and nothing was lost between them. */
        fun rrHistory(beats: List<LocatedBeat>, fs: Double): DoubleArray {
            val out = ArrayList<Double>(beats.size)
            var last = Double.NaN
            var seen = false
            for (b in beats) {
                val usable = !b.searchBack && !b.flagged
                if (seen) out += if (usable && !last.isNaN() && !b.gap) 1000.0 * (b.pos - last) / fs else Double.NaN
                seen = true
                last = if (usable) b.pos else Double.NaN
            }
            return out.toDoubleArray()
        }

        /** NNSeries.from_intervals: a gap-free list of intervals in ms. */
        fun fromIntervals(nnMs: DoubleArray, clean: Boolean = false): NnSeries {
            require(nnMs.all { it.isFinite() }) { "fromIntervals needs finite intervals" }
            val t = DoubleArray(nnMs.size + 1)
            var s = 0.0
            for (i in nnMs.indices) { s += nnMs[i]; t[i + 1] = s / 1000.0 }
            return if (clean) cleaned(t, nnMs) else NnSeries(t, nnMs.copyOf())
        }

        fun cleaned(t: DoubleArray, rr: DoubleArray): NnSeries {
            if (t.size < 2) return NnSeries(t, DoubleArray(0))
            val acc = BeatDetector.cleanNn(rr).first
            return NnSeries(t, DoubleArray(rr.size) { if (acc[it]) rr[it] else Double.NaN })
        }
    }

    /** The intervals whose two beats both lie in [t0, t1). */
    fun window(t0: Double, t1: Double): NnSeries {
        val k = beatT.indices.filter { beatT[it] >= t0 && beatT[it] < t1 }
        if (k.size < 2) return NnSeries(DoubleArray(k.size) { beatT[k[it]] }, DoubleArray(0))
        return NnSeries(beatT.copyOfRange(k.first(), k.last() + 1), nnMs.copyOfRange(k.first(), k.last()))
    }

    val accepted: BooleanArray get() = BooleanArray(nnMs.size) { nnMs[it].isFinite() }
    val nIntervals: Int get() = nnMs.size
    val nAccepted: Int get() = nnMs.count { it.isFinite() }
    val coverage: Double get() = if (nIntervals > 0) nAccepted.toDouble() / nIntervals else 0.0
    val validS: Double get() = if (nIntervals > 0) nnMs.filter { it.isFinite() }.sum() / 1000.0 else 0.0
    val spanS: Double get() = if (beatT.size > 1) beatT.last() - beatT.first() else 0.0

    /** Accepted intervals, ms. */
    val values: DoubleArray get() = nnMs.filter { it.isFinite() }.toDoubleArray()

    /** Time (s) of the beat that ends each accepted interval. */
    val times: DoubleArray get() = nnMs.indices.filter { nnMs[it].isFinite() }.map { beatT[it + 1] }.toDoubleArray()

    /** (a, b): every accepted interval a immediately followed by an accepted b. */
    fun pairs(): Pair<DoubleArray, DoubleArray> {
        val k = (0 until maxOf(nnMs.size - 1, 0)).filter { nnMs[it].isFinite() && nnMs[it + 1].isFinite() }
        return Pair(DoubleArray(k.size) { nnMs[k[it]] }, DoubleArray(k.size) { nnMs[k[it] + 1] })
    }

    /** Maximal stretches of consecutive accepted intervals at least [minLen] long. */
    fun runs(minLen: Int = 1): List<DoubleArray> {
        val out = ArrayList<DoubleArray>()
        var i = 0
        val n = nnMs.size
        while (i < n) {
            if (!nnMs[i].isFinite()) { i++; continue }
            var j = i
            while (j < n && nnMs[j].isFinite()) j++
            if (j - i >= minLen) out += nnMs.copyOfRange(i, j)
            i = j
        }
        return out
    }
}

/** core.gate: null when the window meets the measure's minimum duration, NN
 *  count and coverage, otherwise the reason it does not. */
fun gate(nn: NnSeries, name: String): String? {
    val req = AlgConfig.MIN_WINDOW.getValue(name)
    if (nn.validS < req.validS) return "${f0(nn.validS)} s of valid NN intervals, needs ${g(req.validS)} s"
    if (req.nn != null && nn.nAccepted < req.nn) return "${nn.nAccepted} accepted NN intervals, needs ${req.nn}"
    if (req.coverage != null && nn.coverage < req.coverage)
        return "coverage ${f0(100 * nn.coverage)}%, needs ${f0(100 * req.coverage)}%"
    return null
}

/** core.result: a non-finite value is withheld as "not finite". */
internal fun result(
    nn: NnSeries, name: String, unit: String, value: Double? = null, withheld: String? = null,
    nUsed: Int = 0, extra: Map<String, Double> = emptyMap(),
): Result {
    val bad = value != null && !value.isFinite()
    return Result(
        name, if (bad) null else value, unit, if (bad) "not finite" else withheld,
        nUsed, nn.validS, nn.spanS, nn.coverage, extra,
    )
}

// ------------------------------------------------- Python number formatting
// The withheld reasons are compared with Python's word for word, so numbers in
// them are formatted as Python's f-strings do: exact binary value, rounded
// half to even, never the device locale.

/** f"{x:.0f}" */
internal fun f0(x: Double): String = BigDecimal(x).setScale(0, RoundingMode.HALF_EVEN).toPlainString()

/** f"{x:.1f}" */
internal fun f1(x: Double): String = BigDecimal(x).setScale(1, RoundingMode.HALF_EVEN).toPlainString()

/** f"{x:g}" for the plain constants used here (60.0 -> "60", 0.4 -> "0.4"). */
internal fun g(x: Double): String =
    if (x == Math.rint(x) && kotlin.math.abs(x) < 1e6) x.toLong().toString()
    else BigDecimal(x.toString()).stripTrailingZeros().toPlainString()

// ------------------------------------------------------ numpy equivalents

internal fun mean(v: DoubleArray): Double = v.sum() / v.size

/** np.std(v, ddof=1) */
internal fun stdDdof1(v: DoubleArray): Double {
    val m = mean(v)
    var s = 0.0
    for (x in v) s += (x - m) * (x - m)
    return kotlin.math.sqrt(s / (v.size - 1))
}

/** np.median */
internal fun median(v: DoubleArray): Double {
    val s = v.sortedArray(); val m = s.size / 2
    return if (s.size % 2 == 1) s[m] else (s[m - 1] + s[m]) / 2.0
}

/** np.linspace(lo, hi, n): lo + i * step, with the last point exactly hi. */
internal fun linspace(lo: Double, hi: Double, n: Int): DoubleArray {
    val step = (hi - lo) / (n - 1)
    return DoubleArray(n) { if (it == n - 1) hi else it * step + lo }
}

/** np.trapezoid(y, x) */
internal fun trapezoid(y: DoubleArray, x: DoubleArray): Double {
    var s = 0.0
    for (i in 0 until y.size - 1) s += (x[i + 1] - x[i]) * (y[i + 1] + y[i]) / 2.0
    return s
}

/** np.polyfit(x, y, 1): (slope, intercept), least squares. */
internal fun linearFit(x: DoubleArray, y: DoubleArray): Pair<Double, Double> {
    val mx = mean(x); val my = mean(y)
    var sxy = 0.0; var sxx = 0.0
    for (i in x.indices) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) * (x[i] - mx) }
    val slope = sxy / sxx
    return Pair(slope, my - slope * mx)
}
