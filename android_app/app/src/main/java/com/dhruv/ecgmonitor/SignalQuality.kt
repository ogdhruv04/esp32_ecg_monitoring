package com.dhruv.ecgmonitor

import kotlin.math.sqrt

/**
 * Rolling signal-quality estimate over the display window.
 *
 * Given an episodic finger measurement, the most valuable thing this pipeline
 * can output is a trustworthy "is this reading interpretable?" decision. A wrong
 * heart rate is far worse than an honest "recording failed, try again" - so this
 * gates the number rather than decorating it.
 *
 * Two features, both computable without any reference recording:
 *  - kSQI: kurtosis. Clean ECG is spiky (>5); gaussian noise sits near 3.
 *  - pSQI: share of power in the 5-15 Hz QRS band vs total.
 *
 * bSQI (agreement between two independent detectors) is the strongest feature
 * and is what the MIT-BIH benchmark gates on, but it needs a second detector
 * running concurrently. Not implemented on-device yet - see the benchmark for
 * what it is worth (Se 98.49 -> 99.54, P+ 97.31 -> 99.41, at 11.9% of
 * recording time rejected).
 */
class SignalQuality(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {

    enum class Level { GOOD, FAIR, POOR }

    data class Result(val level: Level, val kSqi: Double, val pSqi: Double, val label: String)

    fun assess(filtered: FloatArray, qrsBand: FloatArray): Result {
        if (filtered.size < fs.toInt()) {
            return Result(Level.POOR, 0.0, 0.0, "waiting for data")
        }

        val mean = filtered.average()
        var m2 = 0.0; var m4 = 0.0
        for (v in filtered) { val d = v - mean; val d2 = d * d; m2 += d2; m4 += d2 * d2 }
        m2 /= filtered.size; m4 /= filtered.size
        val kSqi = if (m2 > 0) m4 / (m2 * m2) else 0.0

        // pSQI as an energy ratio in the time domain: the 5-15 Hz bandpassed
        // signal (already computed for beat detection) against the full-band
        // signal. Avoids running an FFT every frame for the same information.
        var pTot = 0.0; for (v in filtered) pTot += v.toDouble() * v
        var pQrs = 0.0; for (v in qrsBand) pQrs += v.toDouble() * v
        val pSqi = if (pTot > 0) (pQrs / pTot).coerceIn(0.0, 1.0) else 0.0

        val level = when {
            kSqi >= 5.0 && pSqi >= 0.10 -> Level.GOOD
            kSqi >= 3.5 && pSqi >= 0.05 -> Level.FAIR
            else -> Level.POOR
        }
        val label = when (level) {
            Level.GOOD -> "good contact"
            Level.FAIR -> "marginal - hold still"
            Level.POOR -> "too noisy to read"
        }
        return Result(level, kSqi, pSqi, label)
    }
}
