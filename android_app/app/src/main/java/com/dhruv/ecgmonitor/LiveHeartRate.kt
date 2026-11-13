package com.dhruv.ecgmonitor

import com.dhruv.ecgmonitor.algorithms.median
import kotlin.math.abs

/**
 * The heart rate the main, recording and guided-breathing screens show, from
 * the beats the detector locates.
 *
 * It replaced BeatDetector.heartRate (13 Nov 2026), the median of the
 * detector's last 8 integrator-peak intervals. That window exists to set the
 * search-back threshold, so it has to stay as it is, but as a display it had
 * no age limit and no plausibility test. On the tb02 replay it showed 27 bpm
 * on a GOOD signal, then 101, against a 77 bpm session rate: its 8 intervals
 * still held detections on electrode-settling transients 2-3.4 s apart from
 * up to 25 s earlier, then 250 ms double detections while the threshold
 * recovered (analysis/app_live_hr.txt).
 *
 * The rule: take the intervals between consecutive located beats whose later
 * beat lies in the last WINDOW_S, leaving out any interval across lost
 * samples. An interval is good when it is 300-2000 ms and within NN_STEP (20%)
 * of the interval just before it: a heart rate changes gradually from beat to
 * beat, and a missed or extra beat does not. The bounds are those of the NN
 * cleaning (pan_tompkins.clean_nn). The rate is 60 000 / median of the good
 * intervals, shown only when there are at least MIN_GOOD of them, they are at
 * least MIN_GOOD_SHARE of the window, and the newest beat is not overdue (no
 * more than OVERDUE x that median ago). Otherwise null: the screens say
 * "Measuring" rather than show a wrong number.
 *
 * Flagged and searched-back beats count: the rate needs a beat's presence,
 * not its tp3 timing (the session's heart rate counts them the same way).
 */
class LiveHeartRate(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {
    private class Beat(val pos: Double, val gap: Boolean)
    private val beats = ArrayDeque<Beat>()

    fun onBeat(b: LocatedBeat) {
        beats.addLast(Beat(b.pos, b.gap))
        // One interval before the window is needed, to judge the window's first.
        while (beats.size > 2 && beats[1].pos < beats.last().pos - (WINDOW_S + 3.0) * fs) beats.removeFirst()
    }

    /** The rate at absolute sample index [now], or null. */
    fun bpm(now: Long): Double? {
        val t0 = now - WINDOW_S * fs
        var total = 0
        val good = ArrayList<Double>()
        var prev = Double.NaN                      // previous gap-free interval, ms
        for (i in 1 until beats.size) {
            val b = beats[i]
            if (b.gap) { prev = Double.NaN; continue }
            val ms = 1000.0 * (b.pos - beats[i - 1].pos) / fs
            if (b.pos > t0 && b.pos <= now) {
                total++
                if (ms in NN_MIN_MS..NN_MAX_MS && !prev.isNaN() && abs(ms - prev) <= NN_STEP * prev) good += ms
            }
            prev = ms
        }
        if (good.size < MIN_GOOD || good.size < MIN_GOOD_SHARE * total) return null
        val med = median(good.toDoubleArray())
        if (now - beats.last().pos > OVERDUE * med * fs / 1000.0) return null
        return 60000.0 / med
    }

    companion object {
        const val WINDOW_S = 10.0
        const val MIN_GOOD = 5
        const val MIN_GOOD_SHARE = 0.75
        const val OVERDUE = 2.0
        // pan_tompkins.clean_nn's bounds (BeatDetector.cleanNn).
        const val NN_MIN_MS = 300.0
        const val NN_MAX_MS = 2000.0
        const val NN_STEP = BeatDetector.NN_STEP
    }
}
