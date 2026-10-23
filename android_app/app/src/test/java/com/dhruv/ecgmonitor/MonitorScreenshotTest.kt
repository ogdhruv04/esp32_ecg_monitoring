package com.dhruv.ecgmonitor

import android.content.Context
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import androidx.compose.ui.unit.dp
import java.io.File

/**
 * Renders the main screen from the bundled replay captures at a fixed point
 * in each recording, so the images are reproducible run to run. Each case
 * asserts the quality state it is meant to show, so a render can't silently
 * depict the wrong one.
 *
 * Device config is the test phone (Galaxy A56, SM-A566E): 1080 x 2340 px at
 * logical density 450, i.e. 384 x 832 dp. The app is edge-to-edge, so the
 * render is the whole screen; the phone's bar insets (status 101 px, nav
 * 135 px) and physical DPI (386.37 x 388.47, not 450) are passed in, so a
 * render lines up with an `adb screencap` and the grid is in the phone's real
 * millimetres. Robolectric draws no system bars, so those strips are empty.
 *
 * Images go to android_app/screenshots/after/. screenshots/before/ is the
 * frozen pre-redesign baseline and is never written.
 */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w384dp-h832dp-port-450dpi")
class MonitorScreenshotTest {

    @get:Rule val compose = createComposeRule()

    private fun capture(
        name: String, status: String, pipeline: EcgPipeline, receiving: Boolean,
        gain: Int = GAINS_MM_PER_MV[0],
    ) {
        compose.setContent {
            MonitorContent(
                status = status, p = pipeline, tick = 0, receiving = receiving,
                gainMmPerMv = gain, onCycleGain = {},
                xdpi = A56_XDPI, ydpi = A56_YDPI,
                insets = PaddingValues(top = pxToDp(A56_STATUS_BAR_PX), bottom = pxToDp(A56_NAV_BAR_PX)),
            )
        }
        val dir = File(System.getProperty("screenshots.dir") ?: error("run via Gradle"), "after")
        compose.onRoot().captureRoboImage(File(dir, "roborazzi_$name.png").path)
    }

    private fun render(asset: String, expected: SignalQuality.Level, gain: Int = GAINS_MM_PER_MV[0]) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val packets = context.assets.open("${EcgViewModel.REPLAY_DIR}/$asset.csv")
            .use { CaptureReplay.packets(it) }
        val pipeline = EcgPipeline()
        val until = (AT_SECONDS * EcgFilter.ECG_SAMPLE_RATE).toLong()
        packets.takeWhile { it.sampleOffset < until }.forEach { pipeline.onPacket(it.packet) }
        assertEquals("$asset at ${AT_SECONDS}s", expected, pipeline.signalQuality.level)
        // The status line the ViewModel shows during a replay.
        val name = if (gain == GAINS_MM_PER_MV[0]) asset else "${asset}_gain$gain"
        capture(name, "Replay $asset.csv", pipeline, receiving = true, gain = gain)
    }

    @Test fun dual03Good() = render("dual03_ring", SignalQuality.Level.GOOD)
    @Test fun dual02Fair() = render("dual02_ring", SignalQuality.Level.FAIR)
    @Test fun dual01Poor() = render("dual01_ring", SignalQuality.Level.POOR)

    // The signal is small at the nominal scale, so the top gain is the one
    // likely in use; check it stays legible and inside the strip.
    @Test fun dual03GoodAt40() = render("dual03_ring", SignalQuality.Level.GOOD, gain = 40)

    // Scanning, nothing received yet: grid only, no trace.
    @Test fun noPackets() = capture("no_packets", "Scanning for ESP32-ECG...", EcgPipeline(), receiving = false)

    private fun pxToDp(px: Int) = (px / A56_DENSITY).dp

    companion object {
        // Matches the 20 s device screenshot. All three recordings sit in
        // their intended state here.
        const val AT_SECONDS = 20.0

        // Measured on the phone (screenshots/after/device_check.txt).
        const val A56_DENSITY = 450 / 160f
        const val A56_XDPI = 386.3662f
        const val A56_YDPI = 388.47058f
        const val A56_STATUS_BAR_PX = 101
        const val A56_NAV_BAR_PX = 135
    }
}
