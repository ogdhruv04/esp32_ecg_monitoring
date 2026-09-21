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
 * records / 27,574 beats, resampled to this exact 256 SPS rate:
 *
 *     ungated                      Se 98.49%   P+ 97.31%
 *     with bSQI >= 0.9 gate        Se 99.52%   P+ 99.30%   (13.3% rejected)
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
    private val rrHist = ArrayDeque<Long>()
    private var prev = 0.0
    private var rising = false
    private val refractory = (0.200 * fs).toLong()   // absolute cardiac refractory
    private val warmup = (2.0 * fs).toLong()

    private val pendingIdx = ArrayDeque<Long>()
    private val pendingVal = ArrayDeque<Double>()

    /** Feed one filtered sample. Returns the sample index of a confirmed R-peak, or null. */
    /** Last 5-15 Hz bandpassed value. Exposed so SignalQuality can compute a
     *  real QRS-band energy ratio instead of comparing the signal to itself. */
    var lastBandpassed: Float = 0f
        private set

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

        // Search-back: no beat within 166% of the running average RR means one
        // was probably missed under the threshold. Re-scan rejected candidates
        // at half the threshold. Without this, sensitivity on MIT-BIH record
        // 228 was 53.8%; with it, 99.7%.
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
            if (lastPeak > Long.MIN_VALUE / 8) {
                val d = idx - lastPeak
                rr.addLast(d); if (rr.size > 8) rr.removeFirst()
                rrHist.addLast(d); if (rrHist.size > 256) rrHist.removeFirst()
            }
            lastPeak = idx
            pendingIdx.clear(); pendingVal.clear()
            return refine()
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
        if (lastPeak > Long.MIN_VALUE / 8) {
            rr.addLast(bestIdx - lastPeak); if (rr.size > 8) rr.removeFirst()
        }
        lastPeak = bestIdx
        while (pendingIdx.isNotEmpty() && pendingIdx.first() <= bestIdx) {
            pendingIdx.removeFirst(); pendingVal.removeFirst()
        }
        return refine()
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
    val beatCount: Int get() = rrHist.size

    /** RMSSD in ms over the long RR history. Null until there are enough beats
     *  for the figure to mean anything. Intervals outside 300-2000 ms are
     *  dropped first: a missed beat merges two intervals into one and would
     *  otherwise dominate the result - an unfiltered 8-beat window produced a
     *  reading of 425 ms, which is not a physiological value. */
    val rmssdMs: Double?
        get() {
            if (rrHist.size < MIN_BEATS_FOR_HRV) return null
            val ms = rrHist.map { 1000.0 * it / fs }.filter { it in 300.0..2000.0 }
            if (ms.size < MIN_BEATS_FOR_HRV) return null
            var acc = 0.0; var k = 0
            for (i in 1 until ms.size) {
                val d = ms[i] - ms[i - 1]
                if (abs(d) > 300.0) continue   // ectopic / detector slip
                acc += d * d; k++
            }
            if (k < 5) return null
            return sqrt(acc / k)
        }

    companion object { const val MIN_BEATS_FOR_HRV = 30 }
}
