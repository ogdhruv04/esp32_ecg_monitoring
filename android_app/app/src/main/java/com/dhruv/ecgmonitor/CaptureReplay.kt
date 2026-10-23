package com.dhruv.ecgmonitor

import java.io.InputStream

// Rebuilds the BLE packet stream from a capture CSV (capture.py /
// capture_dual.py format: host_time,index,isr_micros,value,etag,leadoff), so
// a recording can be fed through EcgPipeline.onPacket exactly as the ring
// would send it.
//
// The firmware sends the same decoded sample over serial and BLE, in fixed
// batches of PACKET_SAMPLES consecutive samples (sendEcgSampleOverBle in
// sketch.ino). Batches are counted from the first sample in the file. A batch
// with any sample missing from the CSV becomes a lost packet: its seq number
// is skipped and the pipeline sees a gap, which is how real BLE loss looks.
// A trailing partial batch is never sent, as on the board.
object CaptureReplay {
    const val PACKET_SAMPLES = 6

    // sampleOffset is where the packet's first sample sits, counted from the
    // first sample of the file, so a player can keep lost packets as time holes.
    class Packet(val sampleOffset: Long, val packet: EcgPacket)

    fun packets(csv: InputStream): List<Packet> {
        val lines = csv.bufferedReader().lineSequence().iterator()
        require(lines.hasNext()) { "empty capture" }
        val header = lines.next().split(',')
        val iIndex = header.indexOf("index")
        val iValue = header.indexOf("value")
        val iEtag = header.indexOf("etag")
        require(iIndex >= 0 && iValue >= 0 && iEtag >= 0) { "not a capture CSV: $header" }

        val out = ArrayList<Packet>()
        var first = -1L
        var batch = -1L
        val samples = IntArray(PACKET_SAMPLES)
        var filled = 0
        fun flush() {
            if (batch >= 0 && filled == PACKET_SAMPLES) {
                val seq = (batch % 256).toInt()
                out += Packet(batch * PACKET_SAMPLES, EcgPacket(seq, PACKET_SAMPLES, samples.copyOf()))
            }
        }
        for (line in lines) {
            if (line.isBlank()) continue
            val f = line.split(',')
            // ETAG 6 (empty) and 7 (overflow) carry no sample, and the firmware
            // sends neither over BLE. Fast-recovery samples (1, 3) are sent.
            val etag = f[iEtag].toInt()
            if (etag == 6 || etag == 7) continue
            val index = f[iIndex].toLong()
            if (first < 0) first = index
            val b = (index - first) / PACKET_SAMPLES
            if (b != batch) { flush(); batch = b; filled = 0 }
            val slot = ((index - first) % PACKET_SAMPLES).toInt()
            // A duplicated or out-of-order line breaks the batch; drop it whole.
            if (slot != filled) { filled = -1; continue }
            samples[slot] = f[iValue].toInt()
            filled++
        }
        flush()
        return out
    }
}
