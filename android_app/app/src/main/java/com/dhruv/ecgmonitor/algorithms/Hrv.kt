package com.dhruv.ecgmonitor.algorithms

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.sin
import kotlin.math.sqrt

/*
 * Ports of algorithms/hrv_time.py, hrv_freq.py and hrv_nonlinear.py (Poincare
 * and DFA alpha1; sample entropy is not ported, because it needs 180 s of
 * valid NN time and a 180 s session can never hold that). The definitions,
 * and why each minimum window is what it is, are in those files and in
 * docs/hrv_minimum_windows.md. Nothing crosses a hole in the NN series.
 *
 * Each measure has a *Raw function with no minimum-window check, so the
 * arithmetic itself can be pinned against Python on short real recordings
 * where the gated measure is (rightly) withheld.
 */
object Hrv {

    // ---------------------------------------------------------- time domain

    fun rmssdRaw(a: DoubleArray, b: DoubleArray): Double {
        var s = 0.0
        for (i in a.indices) s += (b[i] - a[i]) * (b[i] - a[i])
        return sqrt(s / a.size)
    }

    fun pnn50Raw(a: DoubleArray, b: DoubleArray): Double =
        100.0 * a.indices.count { abs(b[it] - a[it]) > 50.0 } / a.size

    fun rmssd(nn: NnSeries): Result {
        var why = gate(nn, "rmssd")
        val (a, b) = nn.pairs()
        val need = AlgConfig.MIN_WINDOW.getValue("rmssd").pairs!!
        if (why == null && a.size < need) why = "${a.size} successive differences, needs $need"
        if (why != null) return result(nn, "RMSSD", "ms", withheld = why, nUsed = a.size)
        return result(nn, "RMSSD", "ms", rmssdRaw(a, b), nUsed = a.size)
    }

    fun sdnn(nn: NnSeries): Result {
        val why = gate(nn, "sdnn")
        val v = nn.values
        if (why != null) return result(nn, "SDNN", "ms", withheld = why, nUsed = v.size)
        return result(nn, "SDNN", "ms", stdDdof1(v), nUsed = v.size)
    }

    fun pnn50(nn: NnSeries): Result {
        var why = gate(nn, "pnn50")
        val (a, b) = nn.pairs()
        val need = AlgConfig.MIN_WINDOW.getValue("pnn50").pairs!!
        if (why == null && a.size < need) why = "${a.size} successive differences, needs $need"
        if (why != null) return result(nn, "pNN50", "%", withheld = why, nUsed = a.size)
        return result(nn, "pNN50", "%", pnn50Raw(a, b), nUsed = a.size)
    }

    // ----------------------------------------------------- frequency domain

    /** hrv_freq.lomb_scargle: classic periodogram of mean-removed y(t). */
    fun lombScargle(t: DoubleArray, y: DoubleArray, freqs: DoubleArray): DoubleArray {
        val n = t.size
        val tt = DoubleArray(n) { t[it] - t[0] }
        return DoubleArray(freqs.size) { k ->
            val w = 2.0 * PI * freqs[k]
            var s2 = 0.0; var c2 = 0.0
            for (i in 0 until n) { s2 += sin(2 * w * tt[i]); c2 += cos(2 * w * tt[i]) }
            val tau = atan2(s2, c2) / (2 * w)
            var cc = 0.0; var ss = 0.0; var yc = 0.0; var ys = 0.0
            for (i in 0 until n) {
                val c = cos(w * (tt[i] - tau)); val s = sin(w * (tt[i] - tau))
                cc += c * c; ss += s * s; yc += y[i] * c; ys += y[i] * s
            }
            0.5 * ((if (cc > 0) yc * yc / cc else 0.0) + (if (ss > 0) ys * ys / ss else 0.0))
        }
    }

    /** hrv_freq.band_grid: lo to hi inclusive, step no larger than 1/(oversample * span). */
    fun bandGrid(lo: Double, hi: Double, spanS: Double, oversample: Int = AlgConfig.LOMB_OVERSAMPLE): DoubleArray {
        val n = ceil((hi - lo) * oversample * spanS).toInt() + 1
        return linspace(lo, hi, maxOf(n, 2))
    }

    /** hrv_freq.band_power: integral of the PSD (ms^2/Hz) over one band. */
    fun bandPower(t: DoubleArray, v: DoubleArray, band: DoubleArray): Double {
        val span = t.last() - t.first()
        val f = bandGrid(band[0], band[1], span)
        val m = mean(v)
        val p = lombScargle(t, DoubleArray(v.size) { v[it] - m }, f)
        val psd = DoubleArray(p.size) { 2.0 * p[it] * span / v.size }
        return trapezoid(psd, f)
    }

    /** hrv_freq.frequency_domain without LFnu: {"lf", "hf", "lf_hf"}. */
    fun frequencyDomain(nn: NnSeries): Map<String, Result> {
        val t = nn.times; val v = nn.values
        val n = v.size
        val whyLf = gate(nn, "lf")
        var whyHf = gate(nn, "hf")
        val top = AlgConfig.HF_BAND[1]
        if (whyHf == null && n > 0 && mean(v) / 1000.0 > 1.0 / (2.0 * top))
            whyHf = "mean NN ${f0(mean(v))} ms: beat rate below twice the ${g(top)} Hz band edge"
        val lf = if (whyLf != null) null else bandPower(t, v, AlgConfig.LF_BAND)
        val hf = if (whyHf != null) null else bandPower(t, v, AlgConfig.HF_BAND)
        var why = whyLf ?: whyHf
        if (why == null && !(lf!! > 0.0 && hf!! > 0.0)) why = "no power in a band"
        return mapOf(
            "lf" to result(nn, "LF", "ms^2", lf, whyLf, n),
            "hf" to result(nn, "HF", "ms^2", hf, whyHf, n),
            "lf_hf" to result(nn, "LF/HF", "", if (why != null) null else lf!! / hf!!, why, n),
        )
    }

    // ------------------------------------------------------------- Poincare

    fun sdRaw(a: DoubleArray, b: DoubleArray, sum: Boolean): Double {
        val r = sqrt(2.0)
        return stdDdof1(DoubleArray(a.size) { if (sum) (a[it] + b[it]) / r else (a[it] - b[it]) / r })
    }

    fun poincare(nn: NnSeries): Map<String, Result> {
        val (a, b) = nn.pairs()
        val out = LinkedHashMap<String, Result>()
        for ((key, name, sum) in listOf(Triple("sd1", "SD1", false), Triple("sd2", "SD2", true))) {
            var why = gate(nn, key)
            val need = AlgConfig.MIN_WINDOW.getValue(key).pairs!!
            if (why == null && a.size < need) why = "${a.size} successive pairs, needs $need"
            out[key] = result(nn, name, "ms", if (why != null) null else sdRaw(a, b, sum), why, a.size)
        }
        return out
    }

    // ------------------------------------------------------------------ DFA

    /** hrv_nonlinear.dfa_fluctuations: F(n) over runs of consecutive intervals. */
    fun dfaFluctuations(runs: List<DoubleArray>, scales: IntArray, mean: Double): DoubleArray =
        DoubleArray(scales.size) { si ->
            val n = scales[si]
            val xm = (n - 1) / 2.0
            var sxx = 0.0
            for (i in 0 until n) sxx += (i - xm) * (i - xm)
            var ss = 0.0; var boxes = 0
            for (r in runs) {
                val k = r.size / n
                if (k == 0) continue
                val y = DoubleArray(k * n)
                var c = 0.0
                for (i in 0 until k * n) { c += r[i] - mean; y[i] = c }
                for (box in 0 until k) {
                    var ym = 0.0
                    for (i in 0 until n) ym += y[box * n + i]
                    ym /= n
                    var sxy = 0.0
                    for (i in 0 until n) sxy += (y[box * n + i] - ym) * (i - xm)
                    val slope = sxy / sxx
                    var rs = 0.0
                    for (i in 0 until n) {
                        val res = (y[box * n + i] - ym) - slope * (i - xm)
                        rs += res * res
                    }
                    ss += rs / n
                }
                boxes += k
            }
            if (boxes > 0) sqrt(ss / boxes) else Double.NaN
        }

    /** hrv_nonlinear.dfa_alpha1_raw: slope of log F(n) on log n, n = 4..16. */
    fun dfaAlpha1Raw(runs: List<DoubleArray>): Double {
        val scales = (AlgConfig.DFA_SCALE_MIN..AlgConfig.DFA_SCALE_MAX).toList().toIntArray()
        var total = 0.0; var count = 0
        for (r in runs) { for (x in r) total += x; count += r.size }
        val f = dfaFluctuations(runs, scales, total / count)
        if (!f.all { it > 0 }) return Double.NaN
        return linearFit(DoubleArray(scales.size) { ln(scales[it].toDouble()) }, DoubleArray(f.size) { ln(f[it]) }).first
    }

    fun dfaAlpha1(nn: NnSeries): Result {
        val runs = nn.runs(minLen = AlgConfig.DFA_SCALE_MAX)
        val nUsed = runs.sumOf { it.size }
        var why = gate(nn, "dfa_alpha1")
        val need = AlgConfig.MIN_WINDOW.getValue("dfa_alpha1").nnInRuns!!
        if (why == null && nUsed < need) why = "$nUsed NN intervals in runs of ${AlgConfig.DFA_SCALE_MAX} or more, needs $need"
        if (why != null) return result(nn, "DFA alpha1", "", withheld = why, nUsed = nUsed)
        val alpha = dfaAlpha1Raw(runs)
        if (alpha.isNaN()) return result(nn, "DFA alpha1", "", withheld = "no fluctuation at some box size", nUsed = nUsed)
        return result(nn, "DFA alpha1", "", alpha, nUsed = nUsed)
    }

    /** Every ported HRV measure of one NN series, keyed as in algorithms.hrv(). */
    fun all(nn: NnSeries): Map<String, Result> = LinkedHashMap<String, Result>().apply {
        put("rmssd", rmssd(nn)); put("sdnn", sdnn(nn)); put("pnn50", pnn50(nn))
        putAll(poincare(nn))
        putAll(frequencyDomain(nn))
        put("dfa_alpha1", dfaAlpha1(nn))
    }
}
