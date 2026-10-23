package com.dhruv.ecgmonitor

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Proves the app's packet path (EcgPipeline.onPacket, which MainActivity used
 * to do inline) doesn't change the signal: real recordings are replayed as BLE
 * packets through it, and every beat, heart rate and RMSSD must equal what
 * EcgFilter -> BeatDetector produce when called directly on the same samples.
 *
 * The direct reference takes its skip() counts from the capture's sample
 * offsets, the pipeline from wrapping 8-bit seq numbers, so the two are
 * computed independently.
 */
class ReplayPipelineTest {

    private fun replay(name: String): List<CaptureReplay.Packet> {
        val dir = System.getProperty("captures.dir") ?: error("captures.dir not set; run via Gradle")
        return File(dir, name).inputStream().use { CaptureReplay.packets(it) }
    }

    private class Trace(
        val beats: List<Long>,
        val heartRates: List<Double?>,   // after every packet
        val rmssd: List<Double?>,
        val filtered: FloatArray,        // display buffer at the end
        val qrsBand: FloatArray,
        val skipped: Long,
    )

    private fun throughPipeline(packets: List<CaptureReplay.Packet>): Trace {
        val beats = ArrayList<Long>()
        val p = EcgPipeline(onBeat = { beats += it })
        val hr = ArrayList<Double?>(); val rm = ArrayList<Double?>()
        for (pk in packets) {
            p.onPacket(pk.packet)
            hr += p.heartRate; rm += p.rmssdMs
        }
        return Trace(beats, hr, rm, p.filteredBuffer.snapshot(), p.qrsBuffer.snapshot(), p.samplesSkipped)
    }

    private fun direct(packets: List<CaptureReplay.Packet>): Trace {
        val filter = EcgFilter(); val detector = BeatDetector(); val baseline = BaselineRemover()
        val filtered = EcgRingBuffer(); val qrs = EcgRingBuffer()
        val beats = ArrayList<Long>()
        val hr = ArrayList<Double?>(); val rm = ArrayList<Double?>()
        var next = 0L; var skipped = 0L
        for (pk in packets) {
            val missing = pk.sampleOffset - next
            if (missing > 0) { detector.skip(missing.toInt()); skipped += missing }
            for (v in pk.packet.samples) {
                val f = filter.process(v)
                detector.process(f)?.let { beats += it }
                filtered.push(baseline.process(f)); qrs.push(detector.lastBandpassed)
            }
            next = pk.sampleOffset + pk.packet.samples.size
            hr += detector.heartRate; rm += detector.rmssdMs
        }
        return Trace(beats, hr, rm, filtered.snapshot(), qrs.snapshot(), skipped)
    }

    private fun check(name: String, expectLoss: Boolean) {
        val packets = replay(name)
        val lost = packets.zipWithNext().sumOf { (a, b) ->
            (b.sampleOffset - a.sampleOffset) / CaptureReplay.PACKET_SAMPLES - 1
        }
        assertEquals("$name: packet loss present", expectLoss, lost > 0)

        val app = throughPipeline(packets)
        val ref = direct(packets)
        println("$name: ${packets.size} packets, $lost lost, ${ref.beats.size} beats, " +
            "last HR ${ref.heartRates.last()}, last RMSSD ${ref.rmssd.last()}")

        assertTrue("$name: detector found no beats, test would be vacuous", ref.beats.isNotEmpty())
        assertTrue("$name: no heart rate ever reported", ref.heartRates.any { it != null })
        assertEquals("$name: skipped samples", ref.skipped, app.skipped)
        assertEquals("$name: beats", ref.beats, app.beats)
        assertEquals("$name: heart rate after each packet", ref.heartRates, app.heartRates)
        assertEquals("$name: RMSSD after each packet", ref.rmssd, app.rmssd)
        assertArrayEquals("$name: display buffer", ref.filtered, app.filtered, 0f)
        assertArrayEquals("$name: QRS-band buffer", ref.qrsBand, app.qrsBand, 0f)
    }

    // No host-side gaps: the whole recording arrives as one unbroken stream.
    @Test fun dual03ChestNoLoss() =
        check("20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv", expectLoss = false)

    // One serial gap, so one lost packet and a skip() inside a GOOD recording.
    @Test fun dual03FingerWithLoss() =
        check("20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv", expectLoss = true)

    // Many gaps on a POOR recording, where search-back and stall decay fire.
    @Test fun dual01FingerManyGaps() =
        check("20260929_153252_dual01_c3chest_wroomfinger_ref.csv", expectLoss = true)

    // The replay itself must not drop or reorder samples on a clean capture.
    @Test fun replayKeepsEverySampleOfCleanCapture() {
        val name = "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv"
        val rows = File(System.getProperty("captures.dir"), name).readLines().drop(1)
            .filter { it.isNotBlank() }.map { it.split(',')[3].toInt() }
        val replayed = replay(name).flatMap { it.packet.samples.toList() }
        val whole = rows.size / CaptureReplay.PACKET_SAMPLES * CaptureReplay.PACKET_SAMPLES
        assertEquals(rows.take(whole), replayed)
        assertTrue("seq must wrap at least once", replay(name).any { it.packet.seq == 255 })
    }
}
