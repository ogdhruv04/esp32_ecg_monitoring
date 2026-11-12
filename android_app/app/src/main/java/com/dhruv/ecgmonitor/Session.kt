package com.dhruv.ecgmonitor

import com.dhruv.ecgmonitor.algorithms.AlgConfig
import com.dhruv.ecgmonitor.algorithms.Breathing
import com.dhruv.ecgmonitor.algorithms.Hrv
import com.dhruv.ecgmonitor.algorithms.NnSeries
import com.dhruv.ecgmonitor.algorithms.Result
import com.dhruv.ecgmonitor.algorithms.median

/** session_config.json (version ses1). SessionConfigTest fails on any difference. */
object SessionConfig {
    const val VERSION = "ses1"
    const val DURATION_S = 180.0
    const val TAIL_S = 4.0
    const val HR_MIN_INTERVALS = 30
    const val BR_STEP_S = 3.0
    const val BR_MIN_WINDOWS = 5
}

/**
 * Collects one session from the live sample stream: the filtered samples in
 * [s0, s1) and every beat located with its position in [s0, s1). The detector
 * runs on for TAIL_S after s1 so that beats located late (search-back) are
 * kept. Feed it from EcgPipeline exactly in this order per sample:
 * onSample(f), then BeatDetector.process(f) (beats arrive through onBeat),
 * then checkEnd(); and onSkip(n) right after BeatDetector.skip(n). This is the
 * order session_reference.run_detector stops in, which SessionParityTest pins.
 */
class SessionRecorder(val s0: Long, val s1: Long, private val fs: Double = EcgFilter.ECG_SAMPLE_RATE) {
    val end: Long = s1 + (SessionConfig.TAIL_S * fs).toInt()
    private val y = FloatArray((s1 - s0).toInt()) { Float.NaN }
    private val beats = ArrayList<LocatedBeat>()
    /** Absolute index of the next sample. */
    var index: Long = s0; private set
    var finished = false; private set
    /** Samples inside the session that never arrived. */
    var samplesLost = 0L; private set
    // Quality verdicts seen during the session (EcgPipeline assesses at 4 Hz).
    private val qualityCounts = IntArray(SignalQuality.Level.entries.size)

    val beatCount: Int get() = beats.size
    /** 0..1 through the recorded part (not the tail). */
    val progress: Double get() = ((index - s0).toDouble() / (s1 - s0)).coerceIn(0.0, 1.0)

    fun onSample(f: Float) {
        if (finished) return
        if (index in s0 until s1) y[(index - s0).toInt()] = f
        index++
    }

    fun onSkip(n: Int) {
        if (finished || n <= 0) return
        val a = maxOf(index, s0); val b = minOf(index + n, s1)
        if (b > a) samplesLost += b - a
        index += n
        checkEnd()
    }

    fun onBeat(b: LocatedBeat) {
        if (!finished && b.pos >= s0.toDouble() && b.pos < s1.toDouble()) beats += b
    }

    fun onQuality(level: SignalQuality.Level) {
        if (!finished && index < s1) qualityCounts[level.ordinal]++
    }

    /** True once, when the session has just ended. */
    fun checkEnd(): Boolean {
        if (finished || index < end) return false
        finished = true
        return true
    }

    /** Ends the session now, e.g. when the stream stopped and never came back.
     *  Samples never received count as lost. */
    fun finishEarly() {
        if (finished) return
        if (index < s1) samplesLost += s1 - maxOf(index, s0)
        finished = true
    }

    fun report(): SessionMeasures = SessionMeasures.compute(beats.toList(), y, s0, s1, fs)

    fun qualityShare(level: SignalQuality.Level): Double {
        val total = qualityCounts.sum()
        return if (total == 0) 0.0 else qualityCounts[level.ordinal].toDouble() / total
    }
}

/** Every measure of one session. Port of session_reference.session_report. */
class SessionMeasures(
    val results: Map<String, Result>,
    val windows: List<Pair<Double, Result>>,
    val beats: Int,
    val nn: NnSeries,
) {
    companion object {
        /** The measures on the report, in order (session_reference.KEYS). */
        val KEYS = listOf("hr", "br", "rmssd", "sdnn", "pnn50", "sd1", "sd2", "lf", "hf", "lf_hf", "dfa_alpha1")

        fun compute(beats: List<LocatedBeat>, y: FloatArray, s0: Long, s1: Long, fs: Double): SessionMeasures {
            val nn = NnSeries.fromBeats(beats, fs)
            val hrv = Hrv.all(nn)
            val mods = Breathing.modulations(y, s0, beats, fs)
            val windows = breathingWindows(mods, s0 / fs, s1 / fs)
            val results = LinkedHashMap<String, Result>()
            results["hr"] = heartRate(beats, fs)
            results["br"] = breathing(windows, (s1 - s0) / fs)
            for (k in KEYS.drop(2)) results[k] = hrv.getValue(k)
            return SessionMeasures(results, windows, beats.size, nn)
        }

        /** 60 / median of the gap-free intervals between consecutive beats. */
        fun heartRate(beats: List<LocatedBeat>, fs: Double): Result {
            val rr = (1 until beats.size).filter { !beats[it].gap }
                .map { 1000.0 * (beats[it].pos - beats[it - 1].pos) / fs }.toDoubleArray()
            val nAll = maxOf(beats.size - 1, 0)
            val cov = if (nAll > 0) rr.size.toDouble() / nAll else 0.0
            val span = if (beats.size > 1) (beats.last().pos - beats.first().pos) / fs else 0.0
            val need = SessionConfig.HR_MIN_INTERVALS
            if (rr.size < need)
                return Result("HR", null, "bpm", "${rr.size} beat-to-beat intervals, needs $need", rr.size, span, span, cov)
            return Result("HR", 60000.0 / median(rr), "bpm", null, rr.size, span, span, cov)
        }

        /** The fused rate of every 32 s window starting every BR_STEP_S in [t0, t1). */
        fun breathingWindows(mods: Breathing.Modulations, t0: Double, t1: Double): List<Pair<Double, Result>> {
            val w = AlgConfig.BR_WINDOW_S
            val out = ArrayList<Pair<Double, Result>>()
            var k = 0
            while (k * SessionConfig.BR_STEP_S <= (t1 - t0) - w + 1e-9) {
                val w0 = t0 + k * SessionConfig.BR_STEP_S
                out += w0 to Breathing.rate(mods, w0, w0 + w).getValue("fused")
                k++
            }
            return out
        }

        fun breathing(windows: List<Pair<Double, Result>>, spanS: Double): Result {
            val rates = windows.mapNotNull { it.second.value }.toDoubleArray()
            val m = windows.size
            val cov = if (m > 0) rates.size.toDouble() / m else 0.0
            val need = SessionConfig.BR_MIN_WINDOWS
            if (rates.size < need) {
                val why = if (m > 0) "${rates.size} of $m breathing windows gave a rate, needs $need"
                          else "session shorter than one breathing window"
                return Result("Breathing rate", null, "breaths/min", why, rates.size, spanS, spanS, cov)
            }
            return Result(
                "Breathing rate", median(rates), "breaths/min", null, rates.size, spanS, spanS, cov,
                mapOf("min" to rates.min(), "max" to rates.max(), "windows" to m.toDouble()),
            )
        }
    }
}
