package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.BeatDetector
import com.dhruv.ecgmonitor.LocatedBeat
import kotlin.math.abs

/*
 * Port of algorithms/breathing.py with the frozen alg1 settings: RSA (the
 * accepted NN intervals) and R amplitude (peak to peak, flagged beats
 * measured too), each a Lomb-Scargle spectrum over the breathing band in a
 * 32 s window, fused by agree_or_ramp. The reasoning behind every rule, and
 * the BIDMC validation, are in that file and analysis/breathing_bidmc_*.txt.
 */
object Breathing {

    class Modulations(
        val beatT: DoubleArray,
        val rsaT: DoubleArray, val rsaV: DoubleArray,
        val ampT: DoubleArray, val ampV: DoubleArray,
    )

    /** breathing.r_amplitudes, peak_to_peak with flagged beats: max - min of
     *  the detector's own window around the 5-15 Hz peak. [y] holds samples
     *  [y0, y0 + y.size); a window outside it, or holding a lost (NaN) sample,
     *  gives NaN. */
    fun rAmplitudes(y: FloatArray, y0: Long, beats: List<LocatedBeat>, fs: Double): DoubleArray {
        val lo = (BeatDetector.R_BEFORE_S * fs).toInt()
        val hi = (BeatDetector.R_AFTER_S * fs).toInt()
        return DoubleArray(beats.size) { i ->
            val d = beats[i].bp
            if (d - lo < y0 || d + hi >= y0 + y.size) return@DoubleArray Double.NaN
            var mx = Double.NEGATIVE_INFINITY; var mn = Double.POSITIVE_INFINITY
            for (j in d - lo..d + hi) {
                val v = y[(j - y0).toInt()].toDouble()
                if (v.isNaN()) return@DoubleArray Double.NaN
                if (v > mx) mx = v
                if (v < mn) mn = v
            }
            mx - mn
        }
    }

    fun modulations(y: FloatArray, y0: Long, beats: List<LocatedBeat>, fs: Double): Modulations {
        val nn = NnSeries.fromBeats(beats, fs)
        val amp = rAmplitudes(y, y0, beats, fs)
        val ok = amp.indices.filter { amp[it].isFinite() }
        return Modulations(
            nn.beatT, nn.times, nn.values,
            DoubleArray(ok.size) { nn.beatT[ok[it]] }, DoubleArray(ok.size) { amp[ok[it]] },
        )
    }

    private class Spectrum(val p: DoubleArray?, val why: String?, val n: Int)

    /** breathing._spectrum: normalised spectrum of one series in [t0, t1). */
    private fun spectrum(tAll: DoubleArray, vAll: DoubleArray, t0: Double, t1: Double, nAll: Int, f: DoubleArray): Spectrum {
        val sel = tAll.indices.filter { tAll[it] >= t0 && tAll[it] < t1 }
        var t = DoubleArray(sel.size) { tAll[sel[it]] }
        var v = DoubleArray(sel.size) { vAll[sel[it]] }
        if (v.size >= 3 && AlgConfig.BR_OUTLIER_MAD != 0.0) {
            val med = median(v)
            val mad = 1.4826 * median(DoubleArray(v.size) { abs(v[it] - med) })
            if (mad > 0) {
                val keep = v.indices.filter { abs(v[it] - med) <= AlgConfig.BR_OUTLIER_MAD * mad }
                t = DoubleArray(keep.size) { t[keep[it]] }
                v = DoubleArray(keep.size) { v[keep[it]] }
            }
        }
        if (v.size < AlgConfig.BR_MIN_BEATS)
            return Spectrum(null, "${v.size} usable beats in the window, needs ${AlgConfig.BR_MIN_BEATS}", v.size)
        if (nAll > 0 && v.size.toDouble() / nAll < AlgConfig.BR_MIN_BEAT_COVERAGE)
            return Spectrum(
                null, "${f0(100.0 * v.size / nAll)}% of the window's beats usable, " +
                    "needs ${f0(100 * AlgConfig.BR_MIN_BEAT_COVERAGE)}%", v.size,
            )
        val x = DoubleArray(t.size) { t[it] - t0 }
        val (slope, icept) = linearFit(x, v)
        val vd = DoubleArray(v.size) { v[it] - (slope * x[it] + icept) }
        val p = Hrv.lombScargle(t, vd, f)
        val s = p.sum()
        if (!(s > 0)) return Spectrum(null, "no variation in the series", v.size)
        return Spectrum(DoubleArray(p.size) { p[it] / s }, null, v.size)
    }

    /** breathing._peak: (frequency, share within halfwidth), null when the
     *  maximum sits on a band edge. */
    private fun peak(f: DoubleArray, p: DoubleArray, halfwidthHz: Double): Pair<Double, Double>? {
        var k = 0
        for (i in 1 until p.size) if (p[i] > p[k]) k = i
        if (k == 0 || k == p.size - 1) return null
        val a = p[k - 1]; val b = p[k]; val c = p[k + 1]
        val den = a - 2.0 * b + c
        val fp = f[k] + (if (den < 0) 0.5 * (a - c) / den else 0.0) * (f[1] - f[0])
        var share = 0.0
        for (i in f.indices) if (abs(f[i] - fp) <= halfwidthHz) share += p[i]
        return Pair(fp, share)
    }

    private val NAMES = mapOf("rsa" to "BR (RSA)", "ramp" to "BR (R amplitude)", "fused" to "BR (fused)")

    /** breathing.breathing_rate for the window [t0, t1): {"rsa", "ramp", "fused"}. */
    fun rate(mods: Modulations, t0: Double, t1: Double): Map<String, Result> {
        val w = t1 - t0
        val bt = mods.beatT.filter { it >= t0 && it < t1 }
        val nBeats = bt.size
        fun out(key: String, value: Double? = null, why: String? = null, n: Int = 0, extra: Map<String, Double> = emptyMap()) =
            Result(NAMES.getValue(key), value, "breaths/min", why, n, w, w, if (nBeats > 0) n.toDouble() / nBeats else 0.0, extra)
        fun allWithheld(why: String) = NAMES.keys.associateWith { out(it, why = why) }

        if (w < AlgConfig.BR_WINDOW_S - 1e-9) return allWithheld("window ${g(w)} s, needs ${g(AlgConfig.BR_WINDOW_S)} s")
        if (nBeats < AlgConfig.BR_MIN_BEATS) return allWithheld("$nBeats beats in the window, needs ${AlgConfig.BR_MIN_BEATS}")
        val nyq = 0.5 * (nBeats - 1) / (bt.last() - bt.first())
        val fLo = AlgConfig.BR_BAND_BPM[0] / 60.0
        val fHi = minOf(AlgConfig.BR_BAND_BPM[1] / 60.0, nyq)
        if (fHi <= fLo) return allWithheld("heart rate too low for the breathing band")
        val f = Hrv.bandGrid(fLo, fHi, w, AlgConfig.BR_LOMB_OVERSAMPLE)
        val sp = mapOf(
            "rsa" to spectrum(mods.rsaT, mods.rsaV, t0, t1, nBeats - 1, f),
            "ramp" to spectrum(mods.ampT, mods.ampV, t0, t1, nBeats, f),
        )
        val hw = AlgConfig.BR_SHARE_HALFWIDTH_CYCLES / w
        val smin = AlgConfig.BR_PEAK_SHARE_MIN

        val res = LinkedHashMap<String, Result>()
        val good = HashMap<String, Pair<Int, Pair<Double, Double>>>()   // key -> (n, (freq, share))
        for (key in listOf("rsa", "ramp")) {
            val s = sp.getValue(key)
            if (s.p == null) { res[key] = out(key, why = s.why, n = s.n); continue }
            val pk = peak(f, s.p, hw)
            res[key] = when {
                pk == null -> out(key, why = "no peak inside the breathing band", n = s.n)
                pk.second < smin -> out(
                    key, why = "peak holds ${f0(100 * pk.second)}% of band power, needs ${f0(100 * smin)}%",
                    n = s.n, extra = mapOf("share" to pk.second),
                )
                else -> { good[key] = Pair(s.n, pk); out(key, 60.0 * pk.first, n = s.n, extra = mapOf("share" to pk.second)) }
            }
        }
        val have = sp.filterValues { it.p != null }
        val nMax = have.values.maxOfOrNull { it.n } ?: 0
        res["fused"] = when {
            have.isEmpty() -> out("fused", why = "neither modulation has enough usable beats")
            good.isEmpty() -> out("fused", why = "neither modulation gave a usable peak", n = nMax)
            else -> {
                val a = good["rsa"]?.let { 60.0 * it.second.first }
                val b = good["ramp"]?.let { 60.0 * it.second.first }
                when {
                    a != null && b != null && abs(a - b) <= AlgConfig.BR_AGREE_BPM -> out(
                        "fused", 0.5 * (a + b), n = nMax,
                        extra = mapOf("n_spectra" to 2.0, "share" to minOf(good.getValue("rsa").second.second, good.getValue("ramp").second.second)),
                    )
                    b != null && good.getValue("ramp").second.second >= AlgConfig.BR_RAMP_ALONE_SHARE -> out(
                        "fused", b, n = good.getValue("ramp").first,
                        extra = mapOf("n_spectra" to 1.0, "share" to good.getValue("ramp").second.second),
                    )
                    a != null && b != null -> out(
                        "fused", why = "the two modulations disagree (${f1(a)} and ${f1(b)} breaths/min) and the " +
                            "R-amplitude peak is under ${f0(100 * AlgConfig.BR_RAMP_ALONE_SHARE)}%", n = nMax,
                    )
                    else -> out("fused", why = "no agreement between the modulations and no strong R-amplitude peak", n = nMax)
                }
            }
        }
        return res
    }
}
