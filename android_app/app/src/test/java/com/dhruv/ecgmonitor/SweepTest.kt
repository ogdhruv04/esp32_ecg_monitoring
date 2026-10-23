package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

// The sweep trace's drawing rules, checked on the runs it would draw:
// never across a lost sample, never across the wrap, and an empty erase band
// ahead of the write head.
class SweepTest {

    private fun assertDrawable(buffer: SweepBuffer, columns: Int, erase: Int) {
        val runs = sweepRuns(buffer, columns, erase)
        val head = buffer.total - 1
        for (r in runs) {
            assertTrue("run $r has a lost sample", (r.first..r.last).none { buffer[it].isNaN() })
            assertEquals("run $r crosses the wrap", r.first / columns, r.last / columns)
            assertTrue("run $r inside the erase band", r.first > head - (columns - erase))
        }
    }

    @Test fun gapSplitsTheTrace() {
        val b = SweepBuffer(100)
        repeat(20) { b.push(it.toFloat()) }
        b.skip(6)
        repeat(20) { b.push(it.toFloat()) }
        assertEquals(listOf(SweepRun(0, 19), SweepRun(26, 45)), sweepRuns(b, columns = 80, eraseColumns = 10))
    }

    @Test fun wrapSplitsTheTraceAndEraseBandStaysEmpty() {
        val b = SweepBuffer(200)
        repeat(130) { b.push(1f) }
        // 50 columns, 10 erased: the newest 40 samples (90..129) are shown,
        // split where sample 100 starts a new pass at the left edge.
        assertEquals(listOf(SweepRun(90, 99), SweepRun(100, 129)), sweepRuns(b, columns = 50, eraseColumns = 10))
    }

    @Test fun skipLongerThanTheBufferKeepsTime() {
        val b = SweepBuffer(50)
        repeat(10) { b.push(1f) }
        b.skip(500)
        repeat(10) { b.push(2f) }
        assertEquals(520L, b.total)
        assertEquals(listOf(SweepRun(510, 519)), sweepRuns(b, columns = 40, eraseColumns = 5))
    }

    @Test fun nothingReceivedDrawsNothing() {
        assertEquals(emptyList<SweepRun>(), sweepRuns(SweepBuffer(), columns = 700, eraseColumns = 51))
    }

    // Real recording with one lost packet: the sweep buffer holds the hole,
    // and no run drawn at any point in the replay spans it.
    @Test fun dual03FingerLossLeavesAGap() {
        val file = File(System.getProperty("captures.dir"), "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv")
        val packets = file.inputStream().use { CaptureReplay.packets(it) }
        val p = EcgPipeline()
        var sawGap = false
        for (pk in packets) {
            val before = p.samplesSkipped
            p.onPacket(pk.packet)
            if (p.samplesSkipped > before) {
                val lost = (p.sweepFiltered.total - pk.packet.count - (p.samplesSkipped - before)) until
                    (p.sweepFiltered.total - pk.packet.count)
                assertTrue(lost.all { p.sweepFiltered[it].isNaN() && p.sweepRaw[it].isNaN() })
                sawGap = true
            }
            assertDrawable(p.sweepFiltered, columns = 727, erase = 51)
        }
        assertTrue("expected the recording's lost packet", sawGap)
    }
}
