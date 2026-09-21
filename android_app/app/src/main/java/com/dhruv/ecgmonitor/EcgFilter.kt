package com.dhruv.ecgmonitor

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * Real-time ECG filter chain: 0.5 Hz high-pass -> 50/100 Hz notch -> 40 Hz low-pass.
 *
 * This is the same chain analyze.py runs on the desktop, with one deliberate
 * difference. Offline we filter forward-and-backward (filtfilt), which cancels
 * phase distortion exactly and shifts nothing in time. A live stream has no
 * future samples, so this has to be causal, and a causal filter delays the
 * waveform. See [groupDelaySamples] - it matters the moment anything starts
 * measuring intervals off this output rather than just drawing it.
 *
 * Why this exists at all: the raw signal off the MAX30003 has ~97% of its power
 * at 50 Hz on our bench. Plotting raw ADC codes plots mains hum with the ECG
 * buried inside it.
 */
class EcgFilter(private val sampleRate: Double = ECG_SAMPLE_RATE) {

    /** One biquad section, Direct Form II transposed. */
    private class Biquad(
        val b0: Double, val b1: Double, val b2: Double,
        val a1: Double, val a2: Double
    ) {
        private var z1 = 0.0
        private var z2 = 0.0

        fun process(x: Double): Double {
            val y = b0 * x + z1
            z1 = b1 * x - a1 * y + z2
            z2 = b2 * x - a2 * y
            return y
        }

        fun reset() { z1 = 0.0; z2 = 0.0 }
    }

    private val sections: List<Biquad> = buildList {
        // Baseline wander. Electrode-skin potential drifts as contact pressure
        // and sweat change, walking the trace off-screen. 0.5 Hz is the standard
        // monitoring corner; pushing it higher distorts the ST segment, so the
        // order is raised instead of the corner - steeper rejection below 0.5 Hz
        // with the passband left where it belongs. Two biquads = 4th-order
        // Butterworth, at the standard cascade Q values.
        add(highPass(0.5, 0.5412))
        add(highPass(0.5, 1.3066))

        // Mains. India is 50 Hz. Q=30 keeps the notch narrow - a wide one eats
        // QRS energy along with the hum.
        add(notch(MAINS_HZ, NOTCH_Q))
        // Second harmonic, only if it is actually below Nyquist.
        if (2 * MAINS_HZ < sampleRate / 2) add(notch(2 * MAINS_HZ, NOTCH_Q))

        // EMG and high-frequency junk above the monitoring band. 4th-order
        // Butterworth = two biquads at the standard cascade Q values.
        add(lowPass(40.0, 0.5412))
        add(lowPass(40.0, 1.3066))
    }

    /**
     * Delay this chain introduces at the QRS, in samples.
     *
     * Measured, not estimated: this exact cascade was replicated in Python and
     * cross-correlated against the zero-phase (filtfilt) version of itself over
     * a real 14 s finger-ECG capture at 256 SPS. The peak sits at 2 samples,
     * 7.8 ms. An earlier sampleRate/40 guess gave 6 samples and was wrong by 3x.
     *
     * Re-measure if the cascade or the sample rate changes. Anything that
     * timestamps beats off this output has to subtract it.
     */
    val groupDelaySamples: Int get() = Math.round(sampleRate * 0.0078).toInt()

    val groupDelayMs: Double get() = 1000.0 * groupDelaySamples / sampleRate

    fun process(x: Int): Float {
        var v = x.toDouble()
        for (s in sections) v = s.process(v)
        return v.toFloat()
    }

    fun reset() = sections.forEach { it.reset() }

    // --- RBJ audio-EQ cookbook coefficient design ---------------------------
    // Normalised by a0 up front so the hot path has no division.

    private fun lowPass(freq: Double, q: Double): Biquad {
        val w0 = 2 * PI * freq / sampleRate
        val cosW = cos(w0)
        val alpha = sin(w0) / (2 * q)
        val a0 = 1 + alpha
        return Biquad(
            b0 = ((1 - cosW) / 2) / a0,
            b1 = (1 - cosW) / a0,
            b2 = ((1 - cosW) / 2) / a0,
            a1 = (-2 * cosW) / a0,
            a2 = (1 - alpha) / a0
        )
    }

    private fun highPass(freq: Double, q: Double): Biquad {
        val w0 = 2 * PI * freq / sampleRate
        val cosW = cos(w0)
        val alpha = sin(w0) / (2 * q)
        val a0 = 1 + alpha
        return Biquad(
            b0 = ((1 + cosW) / 2) / a0,
            b1 = (-(1 + cosW)) / a0,
            b2 = ((1 + cosW) / 2) / a0,
            a1 = (-2 * cosW) / a0,
            a2 = (1 - alpha) / a0
        )
    }

    private fun notch(freq: Double, q: Double): Biquad {
        val w0 = 2 * PI * freq / sampleRate
        val cosW = cos(w0)
        val alpha = sin(w0) / (2 * q)
        val a0 = 1 + alpha
        return Biquad(
            b0 = 1.0 / a0,
            b1 = (-2 * cosW) / a0,
            b2 = 1.0 / a0,
            a1 = (-2 * cosW) / a0,
            a2 = (1 - alpha) / a0
        )
    }

    companion object {
        /** Must match ECG_SPS in sketch.ino. */
        const val ECG_SAMPLE_RATE = 256.0
        const val MAINS_HZ = 50.0
        const val NOTCH_Q = 30.0
    }
}
