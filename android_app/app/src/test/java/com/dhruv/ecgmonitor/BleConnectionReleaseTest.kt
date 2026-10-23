package com.dhruv.ecgmonitor

import android.app.Application
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

// BleEcgClient must fully release its GATT when a connection ends or fails;
// one left open stays registered with the Bluetooth stack, and each
// reconnect would leak another. SDK 33, the same sandbox as ReconnectTest.
@RunWith(AndroidJUnit4::class)
@Config(sdk = [33])
class BleConnectionReleaseTest {
    private val app = ApplicationProvider.getApplicationContext<Application>()
    private val ring = SimulatedRing(app)
    private val statuses = mutableListOf<String>()
    private val client = BleEcgClient(app, object : BleEcgListener {
        override fun onStatus(status: String) { statuses += status }
        override fun onPacket(packet: EcgPacket) {}
    })

    private fun idle() = shadowOf(Looper.getMainLooper()).idle()

    @Test fun disconnectClosesTheGatt() {
        client.start()
        ring.advertise()
        ring.connect()
        assertEquals(1, ring.openGatts)
        ring.drop()
        idle()
        assertEquals("Disconnected", statuses.last())
        assertEquals("GATT released on disconnect", 0, ring.openGatts)
        assertEquals("no scan left running", 0, ring.activeScans)
    }

    @Test fun missingCharacteristicClosesTheGatt() {
        client.start()
        ring.advertise()
        ring.connect()
        ring.finishDiscovery()
        idle()
        assertEquals("ECG characteristic not found", statuses.last())
        assertEquals(0, ring.openGatts)
    }

    @Test fun stopAfterDisconnectIsHarmless() {
        client.start()
        ring.advertise()
        ring.connect()
        ring.drop()
        client.stop()
        assertEquals(0, ring.openGatts)
    }
}
