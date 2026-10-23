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
        headline(Link.RECEIVING, null, ready, level, hr, mains)

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

    @Test fun beforeThereIsAVerdictOrARate() {
        assertEquals(Headline.Hidden("Hold still for a few seconds"), h(GOOD, ready = false))
        assertEquals(Headline.Hidden("Measuring"), h(GOOD, hr = null))
    }

    @Test fun noData() {
        val scanning = headline(Link.SCANNING, null, false, POOR, null, 0.0)
        assertEquals("Scanning for ring…", (scanning as Headline.NoData).message)
        val lost = headline(Link.NOT_CONNECTED, "Turn on Bluetooth", true, GOOD, 72.0, 0.0)
        // Stale data must not show through once the link is gone.
        assertEquals(Headline.NoData("Ring not connected", "Turn on Bluetooth"), lost)
    }

    @Test fun bleStatusStrings() {
        assertEquals(Link.SCANNING to null, linkFromStatus("Scanning for ESP32-ECG..."))
        assertEquals(Link.SCANNING to null, linkFromStatus("Subscribed to ECG notifications"))
        assertEquals(Link.NOT_CONNECTED to "Turn on Bluetooth", linkFromStatus("Bluetooth not available/enabled"))
        assertEquals(Link.NOT_CONNECTED to null, linkFromStatus("Disconnected"))
        assertEquals(null, linkFromStatus("something new"))
    }
}
