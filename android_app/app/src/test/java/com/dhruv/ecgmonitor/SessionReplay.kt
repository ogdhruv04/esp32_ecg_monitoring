package com.dhruv.ecgmonitor

import java.io.File

/** Sessions recorded from real captures through EcgPipeline, the way the app
 *  records them, for the session tests and screenshots. */
object SessionReplay {
    fun capturePackets(file: String): List<CaptureReplay.Packet> {
        val dir = System.getProperty("captures.dir") ?: error("captures.dir not set; run via Gradle")
        return File(dir, file).inputStream().use { CaptureReplay.packets(it) }
    }

    /** Feed [packets] until [untilS], starting a session of [durationS] at the
     *  first packet at or after [startS]. Returns the pipeline and the
     *  finished recorder (null if it had not finished by [untilS]). */
    fun run(
        packets: List<CaptureReplay.Packet>, startS: Double, durationS: Double = SessionConfig.DURATION_S,
        untilS: Double = Double.MAX_VALUE,
    ): Pair<EcgPipeline, SessionRecorder?> {
        val p = EcgPipeline()
        var done: SessionRecorder? = null
        p.onSessionEnd = { done = it }
        var started = false
        for (pk in packets) {
            if (pk.sampleOffset >= untilS * EcgFilter.ECG_SAMPLE_RATE) break
            if (!started && pk.sampleOffset >= startS * EcgFilter.ECG_SAMPLE_RATE) { p.startSession(durationS); started = true }
            p.onPacket(pk.packet)
            if (done != null) break
        }
        return p to done
    }

    fun report(rec: SessionRecorder, startedAtMs: Long, replay: String?) =
        SessionReport.from(rec, rec.report(), startedAtMs, replay, endedEarly = false)
}
