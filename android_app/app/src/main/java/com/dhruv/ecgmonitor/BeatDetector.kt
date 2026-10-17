package com.dhruv.ecgmonitor

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Streaming Pan-Tompkins R-peak detector.
 *
 * Direct port of pan_tompkins.py, which is benchmarked against MIT-BIH expert
 * annotations under ANSI/AAMI EC57 by benchmark_mitdb.py. Measured on 12
 * records / 27,574 beats, resampled to this exact 256 SPS rate
 * (analysis/ec57_benchmark.txt):
 *
 *     ungated                      Se 98.50%   P+ 97.31%
 *     with bSQI >= 0.9 gate        Se 99.54%   P+ 99.41%   (11.9% rejected)
 *
 * The phone does not compute bSQI, so the ungated row is the one that applies
 * here. BeatDetectorParityTest checks that this port and pan_tompkins.py find
 * the same beats on a real recording.
 *
 * Those numbers belong to THIS algorithm, not to a library we cannot run here.
 * If you change anything below, the benchmark has to be re-run before the heart
 * rate it feeds is shown to anyone.
 *
 * Feed it the output of [EcgFilter] (before baseline removal), matching what
 * the benchmark filters with.
 */
class BeatDetector(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {

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

    // |bandpassed| history, to map an integrator peak back to the real QRS peak.
    // The integrator lags the complex by ~half a window; reporting its peak
    // directly puts wide complexes outside the 150 ms match window and scores
    // them as a false positive AND a false negative at once.
    private val bpHist = DoubleArray((0.250 * fs).toInt() + 1)
    private var bpI = 0

    private var spk = 0.0
    private var npk = 0.0
    private var n = 0L
    private var lastPeak = Long.MIN_VALUE / 4
    private val rr = ArrayDeque<Long>()
    // Separate, longer RR history for HRV. The 8-interval window above exists to
    // adapt the detection threshold; RMSSD over 8 beats is not a heart-rate
    // variability measurement, it is noise. Real HRV wants minutes.
    //
    // rrHist is measured between REFINED R-peaks, not between the integrator
    // peaks that `rr` and the thresholds use. The integrator peak trails the R
    // peak by a variable amount (sd 26-31 ms on our recordings), and RMSSD,
    // being built from differences of differences, amplifies that jitter: the
    // same finger recording read 58.3 ms from integrator times and 43.8 ms from
    // R-peaks. Detection stays on integrator times, as in pan_tompkins.py.
    private val rrHist = ArrayDeque<Long>()
    private var lastR = NO_BEAT              // refined index of the last primary beat
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

    /** Last 5-15 Hz bandpassed value. Exposed so SignalQuality can compute a
     *  real QRS-band energy ratio instead of comparing the signal to itself. */
    var lastBandpassed: Float = 0f
        private set

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
        n += samples
        gapPending = true
    }

    /** Feed one filtered sample. Returns the sample index of a confirmed R-peak, or null. */
    fun process(x: Float): Long? {
        val y = lp.process(hp.process(x.toDouble()))
        lastBandpassed = y.toFloat()
        bpHist[bpI] = abs(y); bpI = (bpI + 1) % bpHist.size

        for (k in 0 until 4) deriv[k] = deriv[k + 1]
        deriv[4] = y
        val d = (2 * deriv[4] + deriv[3] - deriv[1] - 2 * deriv[0]) / 8.0
        val sq = d * d

        isum += sq - integ[ii]; integ[ii] = sq; ii = (ii + 1) % win
        val mwi = isum / win

        n++
        var out: Long? = null
        if (mwi > prev) rising = true
        else if (rising) { rising = false; out = candidate(prev, n - 1) }
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
        // See analysis/ablation_searchback_refine.txt.
        if (out == null && rr.isNotEmpty()) {
            val avg = rr.sum().toDouble() / rr.size
            if ((n - lastPeak) > 1.66 * avg) out = searchBack()
        }
        return out
    }

    private fun candidate(peak: Double, idx: Long): Long? {
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
            val r = refine()
            if (lastR != NO_BEAT) pushHist(if (gapPending) RR_BREAK else r - lastR)
            lastR = r
            gapPending = false
            lastPeak = idx
            pendingIdx.clear(); pendingVal.clear()
            return r
        }
        npk = 0.875 * npk + 0.125 * peak
        if (idx - lastPeak > refractory) {
            pendingIdx.addLast(idx); pendingVal.addLast(peak)
            if (pendingIdx.size > 64) { pendingIdx.removeFirst(); pendingVal.removeFirst() }
        }
        return null
    }

    private fun searchBack(): Long? {
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
        // A searched-back beat stays out of rrHist, and so does the interval
        // after it: refine() looks back from the current sample, which for a
        // search-back can be over a second past the beat, so its position is
        // unreliable. It goes in as a break, not a silent omission - omitting
        // it let RMSSD difference two intervals that were not adjacent.
        if (lastR != NO_BEAT) pushHist(RR_BREAK)
        lastR = NO_BEAT
        gapPending = false
        lastPeak = bestIdx
        while (pendingIdx.isNotEmpty() && pendingIdx.first() <= bestIdx) {
            pendingIdx.removeFirst(); pendingVal.removeFirst()
        }
        return refine()
    }

    private fun pushHist(d: Long) {
        rrHist.addLast(d); if (rrHist.size > 256) rrHist.removeFirst()
    }

    /** Max of |bandpassed| over the last 200 ms, i.e. index n-1-offset. */
    private fun refine(): Long {
        val back = (0.200 * fs).toInt()
        var bestOff = 0; var bestVal = -1.0
        for (k in 0 until back) {
            val j = ((bpI - 1 - k) % bpHist.size + bpHist.size) % bpHist.size
            if (bpHist[j] > bestVal) { bestVal = bpHist[j]; bestOff = k }
        }
        return n - 1 - bestOff
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

    /** RMSSD over the recent RR window, in ms. Indicative only - a 8-beat
     *  window is far too short for a real HRV figure, which needs minutes. */
    val beatCount: Int get() = rrHist.count { it != RR_BREAK }

    /** RMSSD in ms over the long RR history. Null until there are enough beats
     *  for the figure to mean anything. Intervals outside 300-2000 ms are
     *  dropped first: a missed beat merges two intervals into one and would
     *  otherwise dominate the result - an unfiltered 8-beat window produced a
     *  reading of 425 ms, which is not a physiological value.
     *  A difference is only taken between two valid intervals that were
     *  adjacent in time: dropping a bad interval and then differencing its
     *  neighbours would invent a successive difference that never happened. */
    val rmssdMs: Double?
        get() {
            val ms = rrHist.map { if (it == RR_BREAK) Double.NaN else 1000.0 * it / fs }
            val valid = { v: Double -> v in 300.0..2000.0 }   // false for NaN
            if (ms.count(valid) < MIN_BEATS_FOR_HRV) return null
            var acc = 0.0; var k = 0
            for (i in 1 until ms.size) {
                if (!valid(ms[i]) || !valid(ms[i - 1])) continue
                val d = ms[i] - ms[i - 1]
                if (abs(d) > 300.0) continue   // ectopic / detector slip
                acc += d * d; k++
            }
            if (k < 5) return null
            return sqrt(acc / k)
        }

    companion object {
        const val MIN_BEATS_FOR_HRV = 30
        /** Marks a break in rrHist: a lost-data gap or a searched-back beat. */
        private const val RR_BREAK = -1L
        private const val NO_BEAT = Long.MIN_VALUE
    }
}
