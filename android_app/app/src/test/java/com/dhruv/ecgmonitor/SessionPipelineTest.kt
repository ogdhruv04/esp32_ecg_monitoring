package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A session recorded through EcgPipeline (packets, seq gaps, the order the
 * pipeline calls the recorder in) must be the session SessionParityTest pins:
 * the same as feeding EcgFilter -> BeatDetector -> SessionRecorder directly,
 * with the lost-sample counts taken from the capture's sample offsets instead
 * of from wrapping seq numbers.
 */
class SessionPipelineTest {

    private fun direct(packets: List<CaptureReplay.Packet>, startS: Double): SessionRecorder {
        val filter = EcgFilter(); val d = BeatDetector()
        var rec: SessionRecorder? = null
        d.onLocated = { rec?.onBeat(it) }
        // A hole before the first packet is invisible to the phone (no seq to
        // compare with); both test-board captures start with one, a duplicated
        // first line that drops the first batch.
        var next = packets.first().sampleOffset
        for (pk in packets) {
            // Started where the app starts it: before the packet, so a gap in
            // front of that packet already counts as lost session samples.
            if (rec == null && pk.sampleOffset >= startS * 256)
                rec = SessionRecorder(d.sampleCount, d.sampleCount + (SessionKind.STANDARD.durationS * 256).toLong())
            val missing = pk.sampleOffset - next
            if (missing > 0) { d.skip(missing.toInt()); rec?.onSkip(missing.toInt()); if (rec?.finished == true) break }
            var ended = false
            for (v in pk.packet.samples) {
                val f = filter.process(v)
                rec?.onSample(f); d.process(f)
                if (rec?.checkEnd() == true) { ended = true; break }
            }
            if (ended) break
            next = pk.sampleOffset + pk.packet.samples.size
        }
        return rec!!
    }

    private fun check(file: String, startS: Double) {
        val packets = SessionReplay.capturePackets(file)
        val (_, viaPipeline) = SessionReplay.run(packets, startS)
        assertNotNull("$file: session never finished", viaPipeline)
        val ref = direct(packets, startS)
        val a = viaPipeline!!.report(SessionKind.STANDARD); val b = ref.report(SessionKind.STANDARD)
        assertEquals("$file: session start", ref.s0, viaPipeline.s0)
        assertEquals("$file: samples lost", ref.samplesLost, viaPipeline.samplesLost)
        assertEquals("$file: beats", b.beats, a.beats)
        assertEquals("$file: measures", b.results, a.results)
        assertTrue("$file: no beats, test would be vacuous", a.beats > 100)
        println("$file: ${a.beats} beats, ${viaPipeline.samplesLost} lost, " +
            a.results.entries.joinToString { (k, r) -> "$k=${r.value ?: "-"}" })
    }

    @Test fun testBoard02() = check("20261027_174352_testboard02.csv", 20.0)
    @Test fun testBoard01() = check("20261027_173714_testboard01.csv", 30.0)
}
