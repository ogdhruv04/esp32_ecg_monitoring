package com.dhruv.ecgmonitor

// The per-packet signal path, lifted out of MainActivity so it outlives the
// activity and can be driven by a unit test exactly the way BLE drives it.
// Plain Kotlin, no Android types. Not thread-safe: feed it from one thread
// (the main thread, where BleEcgClient posts its packets).
class EcgPipeline(private val onBeat: ((Long) -> Unit)? = null) {
    // Two views of the same stream. Raw is what the sensor sends; filtered is
    // what is actually readable. Kept side by side because the difference is
    // the whole point - ~97% of raw power on our bench sits at 50 Hz mains.
    val rawBuffer = EcgRingBuffer()
    val filteredBuffer = EcgRingBuffer()
    // Bandpassed 5-15 Hz copy, kept only to feed the pSQI energy ratio.
    val qrsBuffer = EcgRingBuffer()
    val filter = EcgFilter()
    private val baseline = BaselineRemover()
    val detector = BeatDetector()
    private val quality = SignalQuality()

    var lastSeq = -1; private set
    var lastCount = 0; private set
    var packetsSeen = 0; private set
    var packetsLost = 0; private set
    // Samples the detector was told it missed, from packet gaps.
    var samplesSkipped = 0L; private set
    var heartRate: Double? = null; private set
    var rmssdMs: Double? = null; private set

    // Assessed every QUALITY_EVERY samples rather than on every redraw: it
    // walks the whole 5 s window, and the verdict can't change much faster.
    var signalQuality: SignalQuality.Result = quality.assess(FloatArray(0), FloatArray(0))
        private set
    private var sinceQuality = 0

    fun onPacket(packet: EcgPacket) {
        // seq is a byte that wraps at 256. A gap means the notification never
        // arrived, which is 6 missing samples and one corrupted RR interval -
        // so it has to be counted, not just tolerated. The detector is told
        // too, so it keeps time across the hole and drops the RR interval that
        // spans it. Lost packets are assumed to have carried as many samples
        // as the last one that arrived.
        if (lastSeq >= 0) {
            val gap = (packet.seq - lastSeq + 256) % 256 - 1
            if (gap > 0) {
                packetsLost += gap
                detector.skip(gap * lastCount)
                samplesSkipped += gap * lastCount
            }
        }
        lastSeq = packet.seq
        lastCount = packet.count
        packetsSeen++
        for (v in packet.samples) {
            rawBuffer.push(v.toFloat())
            // Detector runs on the filter output, matching what the MIT-BIH
            // benchmark was run against. Baseline removal is display-only and
            // must not sit between them, or the validation numbers stop
            // applying to what is on screen.
            val f = filter.process(v)
            detector.process(f)?.let { onBeat?.invoke(it) }
            filteredBuffer.push(baseline.process(f))
            qrsBuffer.push(detector.lastBandpassed)
        }
        heartRate = detector.heartRate
        rmssdMs = detector.rmssdMs

        sinceQuality += packet.samples.size
        if (sinceQuality >= QUALITY_EVERY) {
            sinceQuality = 0
            signalQuality = quality.assess(filteredBuffer.snapshot(), qrsBuffer.snapshot())
        }
    }

    companion object {
        // 4 Hz at 256 SPS.
        const val QUALITY_EVERY = 64
    }
}
