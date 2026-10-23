package com.dhruv.ecgmonitor

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

// Share of the raw signal's power at mains (50 Hz and its 100 Hz harmonic),
// over the window given. Feeds the "check the reference electrode" cause line
// only: a missing reference electrode shows up as mains on the raw input,
// which the filter then hides from the trace. Not used for any measurement.
//
// Power is summed over DFT bins within +-0.4 Hz of each line, so a mains
// frequency a little off 50.0 still counts. Same metric as
// analysis/mains_share_dual01-03.txt: the 3-wire run (dual03) stays at or
// under 4.2% on both channels; dual01 sits at 88.3-93.3% and dual02 at
// 10.7-85.4%. The dual02 finger channel was GOOD throughout at up to 66.6%,
// because the notch removes mains, so the cue applies only when quality is
// not GOOD.
fun mainsShareOf(raw: FloatArray, fs: Double = EcgFilter.ECG_SAMPLE_RATE): Double {
    val n = raw.size
    if (n < fs) return 0.0
    val mean = raw.average()
    var variance = 0.0
    for (v in raw) { val d = v - mean; variance += d * d }
    variance /= n
    if (variance == 0.0) return 0.0
    var power = 0.0
    for (f0 in doubleArrayOf(50.0, 100.0)) {
        val lo = ((f0 - 0.4) * n / fs).roundToInt()
        val hi = ((f0 + 0.4) * n / fs).roundToInt()
        for (k in lo..hi) {
            var re = 0.0; var im = 0.0
            val w = 2 * PI * k / n
            for (i in 0 until n) {
                val d = raw[i] - mean
                re += d * cos(w * i); im -= d * sin(w * i)
            }
            power += 2 * (re * re + im * im) / (n.toDouble() * n)
        }
    }
    return (power / variance).coerceIn(0.0, 1.0)
}

// At or above this, a non-GOOD signal is blamed on the reference electrode.
// From three recordings of one subject (file above), so uncalibrated.
const val MAINS_REFERENCE_SUSPECT = 0.10
