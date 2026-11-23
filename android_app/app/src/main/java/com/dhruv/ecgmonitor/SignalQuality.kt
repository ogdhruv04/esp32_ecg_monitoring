package com.dhruv.ecgmonitor

/**
 * Rolling signal-quality estimate over the display window.
 *
 * Given an episodic finger measurement, the most valuable thing this pipeline
 * can output is a trustworthy "is this reading interpretable?" decision. A wrong
 * heart rate is far worse than an honest "recording failed, try again" - so this
 * gates the number rather than decorating it.
 *
 * Two features over the last 5 s, both computable without any reference recording:
 *  - kSQI: kurtosis. Clean ECG is spiky (>5); gaussian noise sits near 3.
 *  - pSQI: share of power in the 5-15 Hz QRS band vs total.
 *
 * And one check on size (sqi2, 14 Nov 2026). Kurtosis rewards spikes, so an
 * electrode-settling transient 30 times the size of a beat scored GOOD. The
 * display signal is cut into consecutive 1 s blocks; a block's swing is its
 * maximum minus its minimum; the reference is the median swing of the last 30
 * blocks, the size of an ordinary second. A block whose swing is more than 4
 * times the reference is an artifact, and the verdict is POOR for that block
 * and the 9 after it. The block still being filled counts as soon as its swing
 * so far is over the limit. [track] must be given every display sample.
 *
 * signal_quality.py is the reference implementation and must stay identical:
 * SignalQualityParityTest compares the two on real recordings, and the numbers
 * below are checked against sqi_config.json. Developed on our own recordings,
 * MIT-BIH and the MIT-BIH noise stress test (analysis/sqi_artifact_dev.txt);
 * not validated on unseen data.
 *
 * bSQI (agreement between two independent detectors) is the strongest feature
 * and is what the MIT-BIH benchmark gates on, but it needs a second detector
 * running concurrently. Not implemented on-device yet - see the benchmark for
 * what it is worth (Se 98.49 -> 99.54, P+ 97.31 -> 99.41, at 11.9% of
 * recording time rejected).
 */
class SignalQuality(private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {

    enum class Level { GOOD, FAIR, POOR }

    /**
     * [artifact]: the size check, not kurtosis or band share, made this POOR.
     * [artifactRatio]: the largest swing / reference among the last
     * [HOLD_BLOCKS] blocks and the block being filled.
     */
    data class Result(
        val level: Level, val kSqi: Double, val pSqi: Double, val label: String,
        val artifact: Boolean = false, val artifactRatio: Double = 0.0,
    )

    private val block = (BLOCK_S * fs).toInt()
    private val swings = DoubleArray(MEMORY_BLOCKS)     // ring of the last block swings
    private var swingCount = 0
    private val ratios = DoubleArray(HOLD_BLOCKS)       // ring of swing / reference
    private var ratioCount = 0
    private var reference = 0.0                         // median swing at the last completed block
    private var hold = 0
    private var count = 0                               // samples in the block being filled
    private var lo = 0f
    private var hi = 0f

    /** One display sample, in order. Lost samples are simply not given. */
    fun track(v: Float) {
        if (count == 0) { lo = v; hi = v } else { if (v < lo) lo = v; if (v > hi) hi = v }
        count++
        if (count < block) return
        count = 0
        val swing = hi.toDouble() - lo.toDouble()
        swings[swingCount % MEMORY_BLOCKS] = swing
        swingCount++
        val n = minOf(swingCount, MEMORY_BLOCKS)
        val sorted = swings.copyOf(n).also { it.sort() }
        reference = sorted[(n - 1) / 2]
        ratios[ratioCount % HOLD_BLOCKS] = if (reference > 0) swing / reference else 0.0
        ratioCount++
        if (swing > RATIO_MAX * reference) hold = HOLD_BLOCKS else if (hold > 0) hold--
    }

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

        var ratio = 0.0
        for (i in 0 until minOf(ratioCount, HOLD_BLOCKS)) if (ratios[i] > ratio) ratio = ratios[i]
        var partial = false
        if (count > 0 && reference > 0) {
            val swing = hi.toDouble() - lo.toDouble()
            if (swing / reference > ratio) ratio = swing / reference
            partial = swing > RATIO_MAX * reference
        }
        val artifact = hold > 0 || partial

        val level = if (artifact) Level.POOR else levelWithoutArtifactCheck(kSqi, pSqi)
        val label = when {
            artifact -> "movement artifact - hold still"
            level == Level.GOOD -> "good contact"
            level == Level.FAIR -> "marginal - hold still"
            else -> "too noisy to read"
        }
        return Result(level, kSqi, pSqi, label, artifact, ratio)
    }

    companion object {
        // sqi_config.json; SignalQualityParityTest fails on any difference.
        const val VERSION = "sqi2"
        const val WINDOW_S = 5.0
        const val K_GOOD = 5.0
        const val P_GOOD = 0.10
        const val K_FAIR = 3.5
        const val P_FAIR = 0.05
        const val BLOCK_S = 1.0
        const val MEMORY_BLOCKS = 30
        const val RATIO_MAX = 4.0
        const val HOLD_BLOCKS = 10

        /** The verdict from kurtosis and band share alone, as before sqi2. */
        fun levelWithoutArtifactCheck(kSqi: Double, pSqi: Double): Level = when {
            kSqi >= K_GOOD && pSqi >= P_GOOD -> Level.GOOD
            kSqi >= K_FAIR && pSqi >= P_FAIR -> Level.FAIR
            else -> Level.POOR
        }
    }
}
