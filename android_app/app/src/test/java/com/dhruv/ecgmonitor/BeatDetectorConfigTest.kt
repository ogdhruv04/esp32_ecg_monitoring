package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The timing-point (tp3) and HRV parameters are frozen in tp2_config.json at the repository
 * root, which pan_tompkins.py reads. BeatDetector.kt hard-codes them; this test
 * fails if any constant drifts from the frozen file, so the phone can never run
 * parameters the held-out evaluation did not.
 */
class BeatDetectorConfigTest {

    // Unit tests run with the module directory (android_app/app) as working dir.
    private val json: String by lazy {
        val f = File("../../tp2_config.json")
        assertTrue("tp2_config.json not found at ${f.absolutePath}", f.exists())
        f.readText()
    }

    private fun num(key: String): Double {
        val m = Regex("\"$key\"\\s*:\\s*(-?[0-9.]+)").find(json)
            ?: throw AssertionError("$key missing from tp2_config.json")
        return m.groupValues[1].toDouble()
    }

    @Test fun detectorConstantsMatchFrozenConfig() {
        assertEquals(num("R_BEFORE_S"), BeatDetector.R_BEFORE_S, 0.0)
        assertEquals(num("R_AFTER_S"), BeatDetector.R_AFTER_S, 0.0)
        assertEquals(num("POL_KEEP"), BeatDetector.POL_KEEP.toDouble(), 0.0)
        assertEquals(num("POL_MIN"), BeatDetector.POL_MIN.toDouble(), 0.0)
        assertEquals(num("HIST_S"), BeatDetector.HIST_S, 0.0)
        assertEquals(num("CORR_LAG"), BeatDetector.CORR_LAG.toDouble(), 0.0)
        assertEquals(num("R_MIN"), BeatDetector.R_MIN, 0.0)
        assertEquals(num("TRACK"), BeatDetector.TRACK.toDouble(), 0.0)
        assertTrue("tp2_config.json is not version ${BeatDetector.VERSION}",
            Regex("\"version\"\\s*:\\s*\"${BeatDetector.VERSION}\"").containsMatchIn(json))
    }

    @Test fun hrvConstantsMatchFrozenConfig() {
        assertEquals(num("NN_STEP"), BeatDetector.NN_STEP, 0.0)
        assertEquals(num("NN_SEED"), BeatDetector.NN_SEED.toDouble(), 0.0)
        assertEquals(num("HRV_DEPTH"), BeatDetector.HRV_DEPTH.toDouble(), 0.0)
        assertEquals(num("MIN_BEATS_FOR_HRV"), BeatDetector.MIN_BEATS_FOR_HRV.toDouble(), 0.0)
    }
}
