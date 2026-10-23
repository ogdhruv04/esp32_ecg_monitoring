package com.dhruv.ecgmonitor

import android.app.Application
import android.os.Looper
import android.os.SystemClock
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.time.Duration

// Reconnection after the ring drops, driven through the real ViewModel with
// fake BLE links and Robolectric's clock. BleEcgClient itself never
// reconnects (it posts "Disconnected" and stops), so this is all there is.
//
// SDK 33, unlike every other Robolectric test here, so it gets a sandbox of
// its own. Sharing one with MonitorRecompositionTest made the main looper's
// clock jump by seconds mid-test (a 23 ms idle once advanced 3000 ms), which
// failed the timing assertions in about half of full-suite runs.
@RunWith(AndroidJUnit4::class)
@Config(sdk = [33])
class ReconnectTest {
    private class FakeLink(val listener: BleEcgListener) : BleLink {
        var stopped = false
        override fun start() = listener.onStatus("Scanning for ESP32-ECG...")
        override fun stop() { stopped = true }
    }

    private val links = mutableListOf<FakeLink>()
    // Through a real ViewModelStore, cleared after each test as Android would,
    // so one test's watchdog and reconnect coroutines can't run on into the next.
    private val store = ViewModelStore()
    private val vm = ViewModelProvider(
        store, ViewModelProvider.AndroidViewModelFactory(ApplicationProvider.getApplicationContext<Application>()),
    )[EcgViewModel::class.java].also { it.linkFactory = { l -> FakeLink(l).also(links::add) } }

    @After fun clear() = store.clear()
    private var seq = 0

    private fun idle(ms: Long) = shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(ms))

    // n packets at the firmware's cadence (6 samples, about every 23 ms).
    private fun stream(link: FakeLink, n: Int) = repeat(n) {
        link.listener.onPacket(EcgPacket(seq++ % 256, 6, IntArray(6) { i -> (i * 37) % 11 }))
        idle(23)
    }

    // The next link is started exactly `ms` after the drop, not before.
    private fun assertReconnectsAfter(ms: Long) {
        val before = links.size
        idle(ms - 100)
        assertEquals("no new link before ${ms} ms", before, links.size)
        idle(200)
        assertEquals("new link by ${ms} ms", before + 1, links.size)
    }

    @Test fun reconnectsWithBackoffAndResetsOnData() {
        vm.startBle()
        assertEquals(1, links.size)
        stream(links[0], 50)
        assertEquals(Link.RECEIVING, vm.link)

        links[0].listener.onStatus("Disconnected")
        assertEquals(Link.NOT_CONNECTED, vm.link)
        assertTrue("a lost live stream is the alert", vm.dropped)
        assertEquals("Reconnecting…", vm.linkFix)
        assertTrue("old client closed", links[0].stopped)

        assertReconnectsAfter(1_000)
        // Still the alert while it scans again, not "Scanning for ring…".
        assertEquals(Link.NOT_CONNECTED, vm.link)
        links[1].listener.onStatus("Disconnected")
        assertReconnectsAfter(2_000)
        links[2].listener.onStatus("Scan failed: code 2")
        assertReconnectsAfter(4_000)

        // Data again. The firmware restarts seq at 0 on a new subscription:
        // that must not count as lost packets, but the outage is a gap.
        seq = 0
        stream(links[3], 20)
        assertEquals(Link.RECEIVING, vm.link)
        assertFalse(vm.dropped)
        assertEquals(0, vm.pipeline.packetsLost)
        assertEquals(1, vm.pipeline.streamBreaks)
        assertTrue("outage marked as skipped samples", vm.pipeline.samplesSkipped > 256)

        // Backoff starts over after data.
        links[3].listener.onStatus("Disconnected")
        assertReconnectsAfter(1_000)
    }

    @Test fun callbacksFromAReplacedLinkAreIgnored() {
        vm.startBle()
        stream(links[0], 20)
        links[0].listener.onStatus("Disconnected")
        assertReconnectsAfter(1_000)
        // A late "Disconnected" from the dead client must not start another round.
        links[0].listener.onStatus("Disconnected")
        idle(5_000)
        assertEquals(2, links.size)
        assertEquals(Link.NOT_CONNECTED, vm.link)
    }

    @Test fun silentStallRestartsTheLink() {
        vm.startBle()
        stream(links[0], 20)
        val lastPacket = SystemClock.elapsedRealtime()
        // Packets stop and no "Disconnected" ever arrives.
        idle(EcgViewModel.STALL_MS + 300)
        assertEquals(Link.NOT_CONNECTED, vm.link)
        assertTrue(vm.dropped)
        // The restart is timed from the last packet: not yet...
        idle(lastPacket + EcgViewModel.SILENT_RESTART_MS - 300 - SystemClock.elapsedRealtime())
        assertFalse(links[0].stopped)
        // ...then the open link is closed (within one 250 ms watchdog tick)
        // and a new one follows after the first backoff step.
        idle(600)
        assertTrue(links[0].stopped)
        assertEquals(1, links.size)
        idle(1_000)
        assertEquals(2, links.size)
    }

    // The real BleEcgClient through Robolectric's Bluetooth shadows: ten
    // rounds of connect, data, drop and automatic reconnect must leave no
    // GATT open and at most the one scan that is looking for the ring.
    @Test fun tenReconnectCyclesLeaveNoConnectionOpen() {
        val ring = SimulatedRing(ApplicationProvider.getApplicationContext())
        val real = ViewModelProvider(
            store, ViewModelProvider.AndroidViewModelFactory(ApplicationProvider.getApplicationContext<Application>()),
        )["real", EcgViewModel::class.java]
        real.startBle()
        repeat(10) { cycle ->
            ring.advertise()
            ring.connect()
            idle(50)
            repeat(5) { ring.notifyPacket(it); idle(23) }
            assertEquals("cycle $cycle receiving", Link.RECEIVING, real.link)
            assertEquals("cycle $cycle: one GATT open while connected", 1, ring.openGatts)
            ring.drop()
            idle(50)
            assertEquals("cycle $cycle: dropped GATT released", 0, ring.openGatts)
            // Data flowed, so the backoff is back at 1 s.
            idle(1_100)
            assertEquals("cycle $cycle: scanning again", 1, ring.activeScans)
        }
        assertEquals(10, ring.gatts.size)
        assertEquals("no connection left open after 10 cycles", 0, ring.openGatts)
        assertEquals(1, ring.activeScans)
        assertEquals(0, real.pipeline.packetsLost)
        assertEquals(10, real.pipeline.streamBreaks + 1)
    }

    @Test fun beforeTheFirstConnectionItIsNotAnAlert() {
        vm.startBle()
        links[0].listener.onStatus("Bluetooth not available/enabled")
        assertEquals(Link.NOT_CONNECTED, vm.link)
        assertFalse(vm.dropped)
        assertEquals("Turn on Bluetooth", vm.linkFix)
        // It keeps trying, so turning Bluetooth on is enough.
        assertReconnectsAfter(1_000)
        assertEquals(Link.SCANNING, vm.link)
    }
}
