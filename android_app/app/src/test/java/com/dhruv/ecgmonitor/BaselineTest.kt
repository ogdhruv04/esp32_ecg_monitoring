package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** "Compared with your usual": earlier live sessions only, three or more. */
class BaselineTest {
    private fun report(t: Long, hr: Double?, rmssd: Double?, replay: String? = null) = SessionReport(
        startedAtMs = t, durationS = 180.0, replayFile = replay, beats = 200, samplesLost = 0, goodShare = 1.0,
        endedEarly = false,
        measures = mapOf(
            "hr" to Measure(hr, "bpm", if (hr == null) "x" else null, 200, 180.0, 1.0),
            "rmssd" to Measure(rmssd, "ms", if (rmssd == null) "x" else null, 150, 150.0, 0.9),
            "br" to Measure(null, "breaths/min", "x", 0, 180.0, 0.0),
        ),
    )

    @Test fun buildsUntilThreeEarlierLiveSessions() {
        val now = report(100, 70.0, 30.0)
        val h = listOf(report(10, 60.0, 20.0), report(20, 80.0, 40.0), report(30, 70.0, 35.0, replay = "tb02.csv"), now)
        val b = baselineFor(now, h)
        assertEquals("replays and the session itself don't count", 2, b.sessions)
        assertFalse(b.ready)
    }

    @Test fun medianAndRangeOfEarlierSessions() {
        val now = report(100, 70.0, 30.0)
        val h = listOf(report(10, 60.0, 20.0), report(20, 80.0, null), report(30, 66.0, 40.0), report(40, 90.0, 50.0),
            report(200, 1.0, 1.0), now)
        val b = baselineFor(now, h)
        assertEquals("only sessions before this one", 4, b.sessions)
        assertTrue(b.ready)
        assertEquals(Usual(73.0, 60.0, 90.0, 4), b.usual["hr"])
        assertEquals("withheld values are skipped", Usual(40.0, 20.0, 50.0, 3), b.usual["rmssd"])
        assertNull("no usual from fewer than three values", b.usual["br"])
    }
}
