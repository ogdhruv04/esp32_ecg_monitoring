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
    // What the sweep trace draws: the same raw and filtered streams, but with
    // lost samples kept as gaps (the buffers above just close up over them).
    val sweepRaw = SweepBuffer()
    val sweepFiltered = SweepBuffer()
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
    // False until the first assessment over at least one second of data;
    // before that the verdict is only a placeholder.
    var qualityReady = false
        private set
    // Mains share of the raw window (MainsMeter.kt), assessed with quality.
    var mainsShare = 0.0
        private set
    private var sinceQuality = 0

    // Times the stream restarted after a reconnection.
    var streamBreaks = 0; private set

    // The Session being recorded, if any (Session.kt). It sees every filtered
    // sample, every lost-sample count and every located beat, in the order
    // SessionParityTest pins. [onSessionEnd] fires once, on the sample that
    // completes it.
    var session: SessionRecorder? = null; private set
    var onSessionEnd: ((SessionRecorder) -> Unit)? = null

    // Sliding windows for the guided-breathing screen; always fed, computed
    // only when asked (LiveHrv.snapshot).
    val live = LiveHrv()

    // The heart rate every screen shows (LiveHeartRate.kt), not the
    // detector's own 8-interval threshold window.
    private val liveRate = LiveHeartRate()

    init {
        detector.onLocated = { session?.onBeat(it); live.onBeat(it); liveRate.onBeat(it) }
    }

    /** Start recording a session of [durationS] from the next sample. */
    fun startSession(durationS: Double = SessionKind.STANDARD.durationS): SessionRecorder {
        val s0 = detector.sampleCount
        return SessionRecorder(s0, s0 + (durationS * EcgFilter.ECG_SAMPLE_RATE).toLong()).also { session = it }
    }

    fun cancelSession() { session = null }

    /** Close the running session now (the stream stopped); fires onSessionEnd. */
    fun endSessionEarly() {
        val s = session ?: return
        s.finishEarly()
        endSession(s)
    }

    private fun endSession(s: SessionRecorder) {
        session = null
        onSessionEnd?.invoke(s)
    }

    // Lost samples go to the detector and the session together.
    private fun skipSamples(n: Int) {
        detector.skip(n)
        live.onSkip(n)
        session?.let { it.onSkip(n); if (it.finished) endSession(it) }
    }

    // The stream stopped and is starting again on a new connection, about
    // `samplesMissed` samples later by the wall clock. The firmware restarts
    // seq at 0 on every subscribe, so the next packet's seq says nothing about
    // what was lost: forget the last one rather than count a bogus gap, and
    // tell the detector and the trace about the hole directly.
    fun breakStream(samplesMissed: Int) {
        lastSeq = -1
        streamBreaks++
        if (samplesMissed > 0) {
            skipSamples(samplesMissed)
            samplesSkipped += samplesMissed
            sweepRaw.skip(samplesMissed)
            sweepFiltered.skip(samplesMissed)
        }
    }

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
                skipSamples(gap * lastCount)
                samplesSkipped += gap * lastCount
                sweepRaw.skip(gap * lastCount)
                sweepFiltered.skip(gap * lastCount)
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
            session?.onSample(f)
            live.onSample(f)
            detector.process(f)?.let { onBeat?.invoke(it) }
            session?.let { if (it.checkEnd()) endSession(it) }
            val display = baseline.process(f)
            filteredBuffer.push(display)
            qrsBuffer.push(detector.lastBandpassed)
            sweepRaw.push(v.toFloat())
            sweepFiltered.push(display)
        }
        heartRate = liveRate.bpm(detector.sampleCount)
        rmssdMs = detector.rmssdMs

        sinceQuality += packet.samples.size
        if (sinceQuality >= QUALITY_EVERY) {
            sinceQuality = 0
            val filtered = filteredBuffer.snapshot()
            signalQuality = quality.assess(filtered, qrsBuffer.snapshot())
            qualityReady = filtered.size >= EcgFilter.ECG_SAMPLE_RATE
            if (qualityReady) session?.onQuality(signalQuality.level)
            mainsShare = mainsShareOf(rawBuffer.snapshot())
        }
    }

    companion object {
        // 4 Hz at 256 SPS.
        const val QUALITY_EVERY = 64
    }
}
