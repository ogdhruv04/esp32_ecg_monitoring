package com.dhruv.ecgmonitor.algorithms

import com.dhruv.ecgmonitor.SessionConfig
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The ported constants against algorithms/config.json (frozen alg1) and
 * session_config.json, so the phone can never run parameters the Python
 * validation did not.
 */
class AlgorithmsConfigTest {
    private val alg = JSONObject(Fixtures.repoFile("algorithms/config.json"))
    private val ses = JSONObject(Fixtures.repoFile("session_config.json"))

    @Test fun hrvSettings() {
        assertEquals(alg.getString("version"), AlgConfig.VERSION)
        val h = alg.getJSONObject("hrv")
        val bands = h.getJSONObject("bands_hz")
        for ((name, kotlin) in listOf("lf" to AlgConfig.LF_BAND, "hf" to AlgConfig.HF_BAND)) {
            val b = bands.getJSONArray(name)
            assertEquals("$name low", b.getDouble(0), kotlin[0], 0.0)
            assertEquals("$name high", b.getDouble(1), kotlin[1], 0.0)
        }
        assertEquals(h.getInt("lomb_oversample"), AlgConfig.LOMB_OVERSAMPLE)
        assertEquals(h.getJSONObject("dfa").getInt("scale_min"), AlgConfig.DFA_SCALE_MIN)
        assertEquals(h.getJSONObject("dfa").getInt("scale_max"), AlgConfig.DFA_SCALE_MAX)
    }

    @Test fun minimumWindows() {
        val mw = alg.getJSONObject("hrv").getJSONObject("min_window")
        for ((name, k) in AlgConfig.MIN_WINDOW) {
            val p = mw.getJSONObject(name)
            assertEquals("$name valid_s", p.getDouble("valid_s"), k.validS, 0.0)
            assertEquals("$name nn", p.optInt("nn", -1), k.nn ?: -1)
            assertEquals("$name pairs", p.optInt("pairs", -1), k.pairs ?: -1)
            assertEquals("$name coverage", p.optDouble("coverage", -1.0), k.coverage ?: -1.0, 0.0)
            assertEquals("$name nn_in_runs", p.optInt("nn_in_runs", -1), k.nnInRuns ?: -1)
            // A key the port doesn't know would be a rule the phone ignores.
            val known = setOf("valid_s", "nn", "pairs", "coverage", "nn_in_runs")
            assertEquals("$name has keys the port ignores", emptySet<String>(), p.keySet() - known)
        }
    }

    @Test fun breathingSettings() {
        val b = alg.getJSONObject("breathing")
        assertEquals(b.getDouble("window_s"), AlgConfig.BR_WINDOW_S, 0.0)
        assertEquals(b.getJSONArray("band_bpm").getDouble(0), AlgConfig.BR_BAND_BPM[0], 0.0)
        assertEquals(b.getJSONArray("band_bpm").getDouble(1), AlgConfig.BR_BAND_BPM[1], 0.0)
        assertEquals(b.getInt("lomb_oversample"), AlgConfig.BR_LOMB_OVERSAMPLE)
        assertEquals(b.getInt("min_beats"), AlgConfig.BR_MIN_BEATS)
        assertEquals(b.getDouble("min_beat_coverage"), AlgConfig.BR_MIN_BEAT_COVERAGE, 0.0)
        assertEquals(b.getDouble("outlier_mad"), AlgConfig.BR_OUTLIER_MAD, 0.0)
        assertEquals(b.getDouble("share_halfwidth_cycles"), AlgConfig.BR_SHARE_HALFWIDTH_CYCLES, 0.0)
        assertEquals(b.getDouble("peak_share_min"), AlgConfig.BR_PEAK_SHARE_MIN, 0.0)
        assertEquals(b.getString("amp_mode"), AlgConfig.BR_AMP_MODE)
        assertEquals(b.getBoolean("amp_flagged"), AlgConfig.BR_AMP_FLAGGED)
        assertEquals(b.getString("fusion"), AlgConfig.BR_FUSION)
        assertEquals(b.getDouble("agree_bpm"), AlgConfig.BR_AGREE_BPM, 0.0)
        assertEquals(b.getDouble("ramp_alone_share"), AlgConfig.BR_RAMP_ALONE_SHARE, 0.0)
    }

    @Test fun sessionSettings() {
        assertEquals(ses.getString("version"), SessionConfig.VERSION)
        assertEquals(ses.getDouble("duration_s"), SessionConfig.DURATION_S, 0.0)
        assertEquals(ses.getDouble("tail_s"), SessionConfig.TAIL_S, 0.0)
        assertEquals(ses.getInt("hr_min_intervals"), SessionConfig.HR_MIN_INTERVALS)
        assertEquals(ses.getDouble("breathing_step_s"), SessionConfig.BR_STEP_S, 0.0)
        assertEquals(ses.getInt("breathing_min_windows"), SessionConfig.BR_MIN_WINDOWS)
    }
}
