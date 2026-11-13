package com.dhruv.ecgmonitor

import com.dhruv.ecgmonitor.SignalQuality.Level.FAIR
import com.dhruv.ecgmonitor.SignalQuality.Level.GOOD
import com.dhruv.ecgmonitor.SignalQuality.Level.POOR
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// The heart-rate area's rules (android_app/CLAUDE.md, Screens).
class HeadlineTest {
    private fun h(level: SignalQuality.Level, hr: Double? = 72.4, mains: Double = 0.02, ready: Boolean = true) =
        headline(Link.RECEIVING, null, dropped = false, qualityReady = ready, level = level, heartRate = hr, mainsShare = mains)

    @Test fun onlyGoodShowsANumber() {
        assertEquals(Headline.Rate(72), h(GOOD))
        assertTrue(h(FAIR) is Headline.Hidden)
        assertTrue(h(POOR) is Headline.Hidden)
    }

    @Test fun causeLines() {
        assertEquals(Headline.Hidden("Hold still"), h(FAIR))
        assertEquals(Headline.Hidden("Press your finger fully on the electrode"), h(POOR))
        // Mains on the raw input outranks motion, at FAIR and POOR alike.
        assertEquals(Headline.Hidden("Check the reference electrode"), h(FAIR, mains = 0.79))
        assertEquals(Headline.Hidden("Check the reference electrode"), h(POOR, mains = 0.92))
        // ...but never hides a GOOD reading: the notch removes it.
        assertEquals(Headline.Rate(72), h(GOOD, mains = 0.66))
    }

    @Test fun artifactAsksToHoldStill() {
        // The gate's size check makes the verdict POOR; the contact is fine, something moved.
        val artifact = headline(Link.RECEIVING, null, false, true, POOR, 72.4, 0.02, artifact = true)
        assertEquals(Headline.Hidden("Hold still"), artifact)
        // Before mains: a transient puts broadband energy on the raw input too.
        assertEquals(Headline.Hidden("Hold still"), headline(Link.RECEIVING, null, false, true, POOR, 72.4, 0.92, artifact = true))
    }

    @Test fun beforeThereIsAVerdictOrARate() {
        assertEquals(Headline.Hidden("Hold still for a few seconds"), h(GOOD, ready = false))
        assertEquals(Headline.Hidden("Measuring"), h(GOOD, hr = null))
    }

    @Test fun noData() {
        val scanning = headline(Link.SCANNING, null, false, false, POOR, null, 0.0)
        assertEquals("Scanning for ring…", (scanning as Headline.NoData).message)
        // Before any connection: not an alert, and stale data can't show through.
        assertEquals(
            Headline.NoData("Ring not connected", "Turn on Bluetooth", alert = false),
            headline(Link.NOT_CONNECTED, "Turn on Bluetooth", false, true, GOOD, 72.0, 0.0),
        )
        // A live stream lost this session: the alert.
        assertEquals(
            Headline.NoData("Ring not connected", "Reconnecting…", alert = true),
            headline(Link.NOT_CONNECTED, "Reconnecting…", true, true, GOOD, 72.0, 0.0),
        )
    }

    @Test fun bleStatusStrings() {
        assertEquals(Link.SCANNING to null, linkFromStatus("Scanning for ESP32-ECG..."))
        assertEquals(Link.SCANNING to null, linkFromStatus("Subscribed to ECG notifications"))
        assertEquals(Link.NOT_CONNECTED to "Turn on Bluetooth", linkFromStatus("Bluetooth not available/enabled"))
        assertEquals(Link.NOT_CONNECTED to null, linkFromStatus("Disconnected"))
        assertEquals(Link.NOT_CONNECTED to null, linkFromStatus("Scan failed: code 2"))
        assertEquals(Link.SCANNING to null, linkFromStatus("Found AA:BB:CC:DD:EE:FF, connecting..."))
        assertEquals(null, linkFromStatus("something new"))
    }
}
