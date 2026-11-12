package com.dhruv.ecgmonitor

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Streaming Pan-Tompkins R-peak detector.
 *
 * Direct port of pan_tompkins.py, which is benchmarked against MIT-BIH expert
 * annotations under ANSI/AAMI EC57 by benchmark_mitdb.py on a 12-record subset,
 * resampled to this exact 256 SPS rate. The figures for the current timing
 * point are in analysis/ec57_benchmark_tp2.txt; the phone does not compute
 * bSQI, so the ungated result is the one that applies here.
 * BeatDetectorParityTest checks that this port and pan_tompkins.py give the
 * same beat positions, flags and RMSSD on real recordings.
 *
 * Beat positions are timing point 2 (tp2): the peak of the dominant QRS
 * deflection in the input, with parabolic sub-sample interpolation and an
 * artifact guard, validated against finger-vs-chest recordings in fiducial.py
 * v2. Detection itself (thresholds, search-back, heart rate) still runs on
 * integrator-peak indices, unchanged.
 *
 * Those numbers belong to THIS algorithm, not to a library we cannot run here.
 * If you change anything below, the benchmark has to be re-run before the heart
 * rate it feeds is shown to anyone.
 *
 * Feed it the output of [EcgFilter] (before baseline removal), matching what
 * the benchmark filters with.
 */
class BeatDetector(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {

    /** Called for every beat as it is located, warm-up beats included, in the
     *  order pan_tompkins.py appends to `beats`. Read-only: it changes nothing
     *  in detection. A Session collects its beats through this. */
    var onLocated: ((LocatedBeat) -> Unit)? = null

    /** Absolute index of the next sample, counting skipped ones. */
    val sampleCount: Long get() = n

    private class Biquad(
        val b0: Double, val b1: Double, val b2: Double, val a1: Double, val a2: Double
    ) {
        private var z1 = 0.0; private var z2 = 0.0
        fun process(x: Double): Double {
            val y = b0 * x + z1
            z1 = b1 * x - a1 * y + z2
            z2 = b2 * x - a2 * y
            return y
        }
    }

    private fun rbj(highPass: Boolean, f0: Double, q: Double): Biquad {
        val w0 = 2 * PI * f0 / fs; val c = cos(w0); val al = sin(w0) / (2 * q); val a0 = 1 + al
        val b = if (highPass) doubleArrayOf((1 + c) / 2, -(1 + c), (1 + c) / 2)
                else          doubleArrayOf((1 - c) / 2, 1 - c, (1 - c) / 2)
        return Biquad(b[0] / a0, b[1] / a0, b[2] / a0, (-2 * c) / a0, (1 - al) / a0)
    }

    // Stage 1: bandpass 5-15 Hz. Narrower than the monitoring band on purpose -
    // centred on QRS energy, and it suppresses P and T waves so they cannot be
    // mistaken for R-peaks.
    private val hp = rbj(true, 5.0, 0.7071)
    private val lp = rbj(false, 15.0, 0.7071)

    private val deriv = DoubleArray(5)
    private val win = (0.150 * fs).toInt()          // ~QRS width
    private val integ = DoubleArray(win)
    private var ii = 0
    private var isum = 0.0

    // History of the input and of |bandpassed|, indexed by absolute sample
    // number (slot i % H). The integrator peaks ~half a window (75 ms) after
    // the QRS, so the beat is located back in these. Search-back can refine a
    // beat up to ~3.5 s old, hence 4 s. Slots skipped by skip() hold NaN, so no
    // window can silently read stale data.
    private val histLen = (HIST_S * fs).toInt()
    private val xHist = DoubleArray(histLen) { Double.NaN }
    private val bpHist = DoubleArray(histLen) { Double.NaN }

    private var spk = 0.0
    private var npk = 0.0
    private var n = 0L
    private var lastPeak = Long.MIN_VALUE / 4
    private val rr = ArrayDeque<Long>()
    private var prev = 0.0
    private var rising = false
    private val refractory = (0.200 * fs).toLong()   // absolute cardiac refractory
    private val warmup = (2.0 * fs).toLong()

    // Threshold decay. A transient far larger than any R-peak - electrodes
    // settling, a knock on the lead - drives SPK so high that nothing reaches
    // the threshold again, and search-back cannot help because no RR history
    // is ever built. The detector then goes silent for the rest of the session:
    // 10 beats in 4.5 minutes on a real chest capture. Halving SPK once a second
    // while no beat is found recovers from any artifact within seconds.
    private val stall = (3.0 * fs).toLong()          // 3 s without a beat = under 20 bpm
    private val decayEvery = (1.0 * fs).toLong()
    private var lastDecay = 0L

    // Set by skip(): samples were lost since the last beat, so the next RR
    // interval spans a hole and may hide a beat. It is not recorded.
    private var gapPending = false

    private val pendingIdx = ArrayDeque<Long>()
    private val pendingVal = ArrayDeque<Double>()

    // tp2 state. A beat is located only once its whole R window has arrived:
    // the integrator often fires less than 60 ms after the 5-15 Hz peak (on
    // 30-70% of beats), and a truncated window shifts the detrend and starves
    // the polarity template. Beats are >= 200 ms apart, so at most one waits,
    // for at most R_AFTER_S.
    private val lo = (R_BEFORE_S * fs).toInt()
    private val hi = (R_AFTER_S * fs).toInt()
    private val segs = ArrayDeque<DoubleArray>()     // previous beats' windows, for polarity
    private class Unfinished(val mwi: Long, val d: Long, val ok: Boolean,
                             val searchBack: Boolean, val gap: Boolean, val warm: Boolean)
    private var unfinished: Unfinished? = null

    // Separate, longer RR history for HRV, in samples between tp2 positions;
    // NaN marks a break (flagged or searched-back beat, or a lost-data gap).
    // The 8-interval `rr` window exists to adapt the detection threshold;
    // RMSSD over 8 beats is noise. Real HRV wants minutes.
    private val rrHist = ArrayDeque<Double>()
    private var lastR = Double.NaN                     // tp2 position of the last usable primary beat
    private var seenBeat = false

    /** Last 5-15 Hz bandpassed value. Exposed so SignalQuality can compute a
     *  real QRS-band energy ratio instead of comparing the signal to itself. */
    var lastBandpassed: Float = 0f
        private set

    /** tp2 position (fractional sample index) of the beat [process] last returned. */
    var lastBeatPosition: Double = Double.NaN
        private set

    /** True when that beat could not be located by tp2 (polarity undecided, a
     *  gap in its window, or no true peak in it). Its position then falls back
     *  to the 5-15 Hz peak, and it is kept out of every HRV interval. */
    var lastBeatFlagged: Boolean = false
        private set

    /** Beats flagged by the per-beat correlation check. */
    var corrFlagged: Int = 0
        private set

    /** Beats located before their R window had arrived. Should stay 0. */
    var clamped: Int = 0
        private set

    private fun xAt(i: Long): Double =
        if (i >= 0 && i >= n - histLen && i <= n - 1) xHist[(i % histLen).toInt()] else Double.NaN

    private fun bpAt(i: Long): Double =
        if (i >= 0 && i >= n - histLen && i <= n - 1) bpHist[(i % histLen).toInt()] else Double.NaN

    /**
     * Tell the detector that [samples] samples were lost in transit.
     *
     * The clock moves on by the lost count, so later beat indices and RR
     * intervals stay on the true timeline. Feeding nothing would compress time:
     * one lost BLE packet would shorten an RR interval by 23 ms. The interval
     * spanning the gap is dropped rather than recorded, because a beat may have
     * fallen inside the hole. The filters are not reset; the splice is a small
     * step they absorb.
     */
    fun skip(samples: Int) {
        if (samples <= 0) return
        var i = n
        while (i < n + minOf(samples, histLen)) {
            val s = (i % histLen).toInt(); xHist[s] = Double.NaN; bpHist[s] = Double.NaN; i++
        }
        n += samples
        gapPending = true
    }

    /** Feed one filtered sample. Returns the sample index (rounded tp2 position)
     *  of a confirmed beat, or null; [lastBeatPosition] has the exact position. */
    fun process(x: Float): Long? {
        val xd = x.toDouble()
        val y = lp.process(hp.process(xd))
        lastBandpassed = y.toFloat()
        val slot = (n % histLen).toInt()
        xHist[slot] = xd; bpHist[slot] = abs(y)

        for (k in 0 until 4) deriv[k] = deriv[k + 1]
        deriv[4] = y
        val d = (2 * deriv[4] + deriv[3] - deriv[1] - 2 * deriv[0]) / 8.0
        val sq = d * d

        isum += sq - integ[ii]; integ[ii] = sq; ii = (ii + 1) % win
        val mwi = isum / win

        n++
        var out: Double? = null
        val u = unfinished
        if (u != null && u.d + hi <= n - 1) out = finish()

        if (mwi > prev) rising = true
        else if (rising) {
            rising = false
            candidate(prev, n - 1)?.let { out = it }
        }
        prev = mwi

        if (n < warmup) {
            spk = maxOf(spk, mwi * 0.25)
            npk = 0.875 * npk + 0.125 * mwi
            return null
        }

        // Recover from a poisoned threshold (see `stall` above).
        if ((n - lastPeak) > stall && (n - lastDecay) > decayEvery) {
            spk = maxOf(npk, spk * 0.5)
            lastDecay = n
        }

        // Search-back: no beat within 166% of the running average RR means one
        // was probably missed under the threshold. Re-scan rejected candidates
        // at half the threshold. Without this, sensitivity on MIT-BIH record
        // 228 is 52.1% (95.7% with it); overall Se 94.86% -> 98.49%.
        // See analysis/ablation_searchback_refine.txt (measured with tp1).
        if (rr.isNotEmpty() && unfinished == null) {
            val avg = rr.sum().toDouble() / rr.size
            if ((n - lastPeak) > 1.66 * avg) searchBack()?.let { out = it }
        }
        val o = out ?: return null
        lastBeatPosition = o
        return o.roundToLong()
    }

    private fun candidate(peak: Double, idx: Long): Double? {
        val thr1 = npk + 0.25 * (spk - npk)
        if (peak > thr1 && (idx - lastPeak) > refractory) {
            // T-wave discrimination: a candidate 200-360 ms after a confirmed
            // beat with under half the amplitude is a T wave, not a beat.
            if (rr.isNotEmpty() && (idx - lastPeak) < 0.36 * fs && peak < 0.5 * spk) {
                npk = 0.875 * npk + 0.125 * peak
                return null
            }
            spk = 0.875 * spk + 0.125 * peak
            if (lastPeak > Long.MIN_VALUE / 8 && !gapPending) {
                rr.addLast(idx - lastPeak); if (rr.size > 8) rr.removeFirst()
            }
            val gap = gapPending
            gapPending = false
            lastPeak = idx
            pendingIdx.clear(); pendingVal.clear()
            return accept(idx, searchBack = false, gap = gap)
        }
        npk = 0.875 * npk + 0.125 * peak
        if (idx - lastPeak > refractory) {
            pendingIdx.addLast(idx); pendingVal.addLast(peak)
            if (pendingIdx.size > 64) { pendingIdx.removeFirst(); pendingVal.removeFirst() }
        }
        return null
    }

    private fun searchBack(): Double? {
        val thr2 = 0.5 * (npk + 0.25 * (spk - npk))
        var bestIdx = -1L; var bestVal = -1.0
        for (k in pendingIdx.indices) {
            val i = pendingIdx.elementAt(k); val v = pendingVal.elementAt(k)
            if (i - lastPeak <= refractory) continue
            if (v > thr2 && v > bestVal) { bestVal = v; bestIdx = i }
        }
        if (bestIdx < 0) return null
        // Lower-confidence detection, so it moves the threshold less.
        spk = 0.75 * spk + 0.25 * bestVal
        if (lastPeak > Long.MIN_VALUE / 8 && !gapPending) {
            rr.addLast(bestIdx - lastPeak); if (rr.size > 8) rr.removeFirst()
        }
        val gap = gapPending
        gapPending = false
        lastPeak = bestIdx
        while (pendingIdx.isNotEmpty() && pendingIdx.first() <= bestIdx) {
            pendingIdx.removeFirst(); pendingVal.removeFirst()
        }
        return accept(bestIdx, searchBack = true, gap = gap)
    }

    // ------------------------------------------------------------- locating

    /** A beat was detected. Locate it now if its R window has arrived (always
     *  so for search-back), otherwise when it has. Returns the position if it
     *  was located now and the warm-up is over. */
    private fun accept(mwiIdx: Long, searchBack: Boolean, gap: Boolean): Double? {
        if (unfinished != null) finish()          // cannot happen at >= 200 ms spacing
        val (d, ok) = bpRefine(mwiIdx)
        unfinished = Unfinished(mwiIdx, d, ok, searchBack, gap, n < warmup)
        if (!ok || d + hi <= n - 1) return finish()
        return null
    }

    private fun finish(): Double? {
        val u = unfinished!!; unfinished = null
        val (sign, tmpl) = polarity()
        var flagged = true
        var pos: Double
        if (u.ok) {
            val (p, f, fallback) = tp2(u.d, sign); pos = p; flagged = f
            // Per-beat CHECK against the median beat (not a per-beat decision): a
            // beat whose window anti-correlates with it is inverted relative to
            // the template - after a real polarity change, the template keeps the
            // old sign for several beats and would time them on the wrong lobe.
            if (!flagged && tmpl != null) {
                val r = corrWith(tmpl, u.d)
                if (!(r >= CORR_MIN)) { pos = fallback; flagged = true; corrFlagged++ }
            }
        } else pos = u.mwi.toDouble()
        // This beat's window joins the polarity template AFTER its own sign was
        // set, and only when the whole window has arrived.
        if (u.ok && u.d + hi <= n - 1) {
            val seg = DoubleArray(lo + hi + 1) { xAt(u.d - lo + it) }
            if (seg.none { it.isNaN() }) {
                segs.addLast(seg); if (segs.size > POL_KEEP) segs.removeFirst()
            }
        }
        // HRV history (pan_tompkins.rr_history is the reference): ONE entry per
        // inter-beat interval, NaN unless both beats are primary and unflagged
        // and nothing was lost between them - so coverage is well defined.
        val usable = !u.searchBack && !flagged
        if (seenBeat) pushHist(if (usable && !lastR.isNaN() && !u.gap) pos - lastR else Double.NaN)
        seenBeat = true
        lastR = if (usable) pos else Double.NaN
        onLocated?.invoke(LocatedBeat(pos, u.d, u.searchBack, flagged, u.gap))
        if (u.warm) return null
        lastBeatFlagged = flagged
        return pos
    }

    /** The 5-15 Hz peak (tp1): max |bandpassed| over the 200 ms ending at the
     *  beat's own integrator index. Up to 23 Oct 2026 this searched back from
     *  the CURRENT sample instead, which for search-back - firing up to 1.66 RR
     *  later - could land on a different beat. */
    private fun bpRefine(mwiIdx: Long): Pair<Long, Boolean> {
        val back = (0.200 * fs).toInt()
        var bestI = mwiIdx; var bestV = -1.0
        for (k in 0 until back) {
            val v = bpAt(mwiIdx - k)
            if (!v.isNaN() && v > bestV) { bestV = v; bestI = mwiIdx - k }
        }
        return Pair(bestI, bestV >= 0.0)
    }

    /** Sign of the median of the previous beats' windows: +1/-1 when one lobe is
     *  at least POL_RATIO x the other, 0 (undecided) otherwise or with fewer than
     *  POL_MIN beats. Never decided from the current beat alone - deciding per
     *  beat is what made the 5-15 Hz peak jump between QRS lobes. */
    private fun polarity(): Pair<Int, DoubleArray?> {
        if (segs.size < POL_MIN) return Pair(0, null)
        val len = segs.first().size
        val col = DoubleArray(segs.size)
        val t = detrend(DoubleArray(len) { i ->
            for (k in segs.indices) col[k] = segs[k][i]
            median(col)
        })
        val pos = t.max(); val neg = -t.min()
        if (pos >= POL_RATIO * neg) return Pair(1, t)
        if (neg >= POL_RATIO * pos) return Pair(-1, t)
        return Pair(0, t)
    }

    /** Correlation of this beat's window with the median beat [t] at the lag
     *  (within +-CORR_LAG samples) where |r| is largest, both detrended and
     *  mean-removed over their overlap. Taking the best alignment matters: the
     *  window is anchored on the 5-15 Hz peak, which can sit +-39 ms off the R
     *  peak, and an unaligned normal beat can correlate negatively with its own
     *  median beat. An inverted beat still gives r near -1. NaN if not computable. */
    private fun corrWith(t: DoubleArray, d: Long): Double {
        val raw = DoubleArray(lo + hi + 1) { xAt(d - lo + it) }
        if (raw.size != t.size || raw.any { it.isNaN() }) return Double.NaN
        val w = detrend(raw)
        val len = w.size
        var best = Double.NaN
        for (lag in -CORR_LAG..CORR_LAG) {
            val i0 = maxOf(0, -lag); val i1 = minOf(len, len - lag)
            val m = i1 - i0
            if (m < len / 2) continue
            var sw = 0.0; var st = 0.0
            for (i in i0 until i1) sw += w[i + lag]
            for (i in i0 until i1) st += t[i]
            val mw = sw / m; val mt = st / m
            var sab = 0.0; var saa = 0.0; var sbb = 0.0
            for (i in i0 until i1) {
                val a = w[i + lag] - mw; val b = t[i] - mt
                sab += a * b; saa += a * a; sbb += b * b
            }
            if (saa <= 0.0 || sbb <= 0.0) continue
            val r = sab / sqrt(saa * sbb)
            if (best.isNaN() || abs(r) > abs(best)) best = r
        }
        return best
    }

    /** R peak + parabolic + guard around the 5-15 Hz peak [d].
     *  Returns (position, flagged, fallback position). */
    private fun tp2(d: Long, sign: Int): Triple<Double, Boolean, Double> {
        val a = bpAt(d - 1); val b = bpAt(d); val c = bpAt(d + 1)
        val fallback = d.toDouble() + (if (!a.isNaN() && !b.isNaN() && !c.isNaN()) parabolic(a, b, c) else 0.0)
        if (sign == 0) return Triple(fallback, true, fallback)
        val start = d - lo
        var end = d + hi
        if (end > n - 1) { end = n - 1; clamped++ }
        val len = (end - start + 1).toInt()
        if (len < 2 * EDGE + 3) return Triple(fallback, true, fallback)
        val w = DoubleArray(len) { sign.toDouble() * xAt(start + it) }
        if (w.any { it.isNaN() }) return Triple(fallback, true, fallback)
        val wd = detrend(w)
        var k = 0
        for (i in 1 until wd.size) if (wd[i] > wd[k]) k = i
        if (k < EDGE || k > wd.size - 1 - EDGE) return Triple(fallback, true, fallback)
        return Triple((start + k).toDouble() + parabolic(wd[k - 1], wd[k], wd[k + 1]), false, fallback)
    }

    private fun pushHist(d: Double) {
        rrHist.addLast(d); if (rrHist.size > HRV_DEPTH) rrHist.removeFirst()
    }

    /** Median of recent RR intervals -> bpm. Median, not mean: one missed beat
     *  doubles an RR interval and would drag a mean badly. Null until stable. */
    val heartRate: Double?
        get() {
            if (rr.size < 4) return null
            val s = rr.toList().sorted()
            val med = if (s.size % 2 == 1) s[s.size / 2].toDouble()
                      else (s[s.size / 2 - 1] + s[s.size / 2]) / 2.0
            if (med <= 0) return null
            val bpm = 60.0 * fs / med
            return if (bpm in 25.0..250.0) bpm else null
        }

    /** Usable intervals in the HRV history (before NN cleaning). */
    val beatCount: Int get() = rrHist.count { !it.isNaN() }

    private fun rrMs(): DoubleArray = DoubleArray(rrHist.size) { 1000.0 * rrHist[it] / fs }

    /** Intervals the NN cleaning dropped from the current HRV history. */
    val nnDropped: Int get() = cleanNn(rrMs()).second

    /** Share (0-1) of the beats in the HRV history whose interval survives into
     *  the NN series. Report it next to RMSSD: an RMSSD from a few surviving
     *  intervals is not the recording's RMSSD. */
    val hrvCoverage: Double
        get() {
            if (rrHist.isEmpty()) return 0.0
            return cleanNn(rrMs()).first.count { it }.toDouble() / rrHist.size
        }

    /** RMSSD in ms on the cleaned NN series of the HRV history; null with fewer
     *  than [MIN_BEATS_FOR_HRV] accepted intervals or 5 differences.
     *  Cleaning (pan_tompkins.clean_nn is the reference): valid = 300-2000 ms; a
     *  valid interval more than 20% from the previous ACCEPTED one is dropped;
     *  the reference is seeded from the median of the first 5 valid intervals and
     *  re-seeded after 5 consecutive drops, so neither one spurious interval nor
     *  a real step change in rate can lock it out. A difference is only taken
     *  between two accepted intervals that are adjacent in time: differencing
     *  across a dropped one would invent a successive difference. */
    val rmssdMs: Double?
        get() {
            val ms = rrMs()
            val acc = cleanNn(ms).first
            var s = 0.0; var k = 0
            for (i in 1 until ms.size) {
                if (acc[i] && acc[i - 1]) { val dd = ms[i] - ms[i - 1]; s += dd * dd; k++ }
            }
            if (acc.count { it } < MIN_BEATS_FOR_HRV || k < 5) return null
            return sqrt(s / k)
        }

    companion object {
        // Frozen in tp2_config.json (version tp2.1); BeatDetectorConfigTest
        // fails if any of these differs from that file.
        const val MIN_BEATS_FOR_HRV = 30
        internal const val HRV_DEPTH = 256
        internal const val NN_STEP = 0.20
        internal const val NN_SEED = 5
        internal const val R_BEFORE_S = 0.100
        internal const val R_AFTER_S = 0.060
        internal const val POL_KEEP = 16
        internal const val POL_MIN = 8
        internal const val POL_RATIO = 1.5
        internal const val EDGE = 2
        internal const val HIST_S = 4.0
        internal const val CORR_MIN = 0.0
        internal const val CORR_LAG = 10

        private fun parabolic(a: Double, b: Double, c: Double): Double {
            val den = a - 2.0 * b + c
            if (!(den < 0.0 && b >= a && b >= c)) return 0.0
            return minOf(0.5, maxOf(-0.5, 0.5 * (a - c) / den))
        }

        private fun detrend(w: DoubleArray): DoubleArray {
            val n = w.size
            val a = (w[0] + w[1] + w[2]) / 3.0
            val b = (w[n - 3] + w[n - 2] + w[n - 1]) / 3.0
            return DoubleArray(n) { i -> w[i] - (a + (b - a) * i / (n - 1)) }
        }

        private fun median(v: DoubleArray): Double {
            val s = v.sortedArray(); val m = s.size / 2
            return if (s.size % 2 == 1) s[m] else (s[m - 1] + s[m]) / 2.0
        }

        /** (accepted mask, dropped count) - see [rmssdMs]. */
        internal fun cleanNn(ms: DoubleArray): Pair<BooleanArray, Int> {
            val acc = BooleanArray(ms.size)
            val valid = ms.indices.filter { !ms[it].isNaN() && ms[it] >= 300.0 && ms[it] <= 2000.0 }
            if (valid.isEmpty()) return Pair(acc, 0)
            var ref = median(DoubleArray(minOf(NN_SEED, valid.size)) { ms[valid[it]] })
            val run = ArrayList<Double>(); var dropped = 0
            for (i in valid) {
                val m = ms[i]
                if (abs(m - ref) > NN_STEP * ref) {
                    dropped++; run.add(m)
                    if (run.size >= NN_SEED) { ref = median(run.toDoubleArray()); run.clear() }
                    continue
                }
                acc[i] = true; ref = m; run.clear()
            }
            return Pair(acc, dropped)
        }
    }
}

/** One located beat, as pan_tompkins.py stores it in `beats`: tp2.1 position
 *  (fractional sample index), the 5-15 Hz peak index [bp], whether it came from
 *  search-back, whether tp2 could not time it, and whether samples were lost
 *  since the previous beat. */
data class LocatedBeat(
    val pos: Double, val bp: Long, val searchBack: Boolean, val flagged: Boolean, val gap: Boolean,
)
