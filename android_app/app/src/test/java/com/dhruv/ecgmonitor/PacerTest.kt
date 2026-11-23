package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 6 breaths a minute: 5 s in, 5 s out, the circle smallest at the start of
 *  each inhale and largest at its end. */
class PacerTest {
    @Test fun sixBreathsAMinute() {
        assertEquals(6.0, 60.0 / (GuidedBreathingConfig.INHALE_S + GuidedBreathingConfig.EXHALE_S), 0.0)
        assertEquals(GuidedBreathingConfig.PACE_PER_MIN, 60.0 / (GuidedBreathingConfig.INHALE_S + GuidedBreathingConfig.EXHALE_S), 0.0)
    }

    @Test fun phases() {
        pacer(0.0).let { assertTrue(it.inhale); assertEquals(0.0, it.size, 1e-12); assertEquals(5.0, it.secondsLeftInPhase, 1e-12) }
        pacer(2.5).let { assertTrue(it.inhale); assertEquals(0.5, it.size, 1e-12) }
        pacer(5.0).let { assertFalse(it.inhale); assertEquals(1.0, it.size, 1e-12); assertEquals(5.0, it.secondsLeftInPhase, 1e-12) }
        pacer(9.0).let { assertFalse(it.inhale); assertEquals(1.0, it.secondsLeftInPhase, 1e-12) }
        pacer(10.0).let { assertTrue(it.inhale); assertEquals(1, it.breath); assertEquals(0.0, it.size, 1e-12) }
        assertEquals(17, pacer(179.9).breath)
    }
}
