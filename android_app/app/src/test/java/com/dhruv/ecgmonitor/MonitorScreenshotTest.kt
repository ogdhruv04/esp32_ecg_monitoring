package com.dhruv.ecgmonitor

import android.content.Context
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
import java.io.File

/**
 * Renders the main screen from the bundled replay captures at a fixed point
 * in each recording, so the images are reproducible run to run. Each case
 * asserts the quality state it is meant to show, so a render can't silently
 * depict the wrong one.
 *
 * Device config is the test phone (Galaxy A56, SM-A566E): 1080 x 2340 px at
 * logical density 450. The app gets 384 x 748 dp of that (the phone's own
 * reported config, between status and navigation bars), so renders are
 * 1080 x 2103 px: the app area of an `adb screencap` (rows 101-2204 on this
 * phone, 2104 px; 748 dp is 2103.75 px and the render rounds down). Its physical
 * DPI is 386, not 450; that matters once the trace is drawn in millimetres.
 *
 * Images go to android_app/screenshots/before/: the screen as it was before
 * the redesign.
 */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w384dp-h748dp-port-450dpi")
class MonitorScreenshotTest {

    @get:Rule val compose = createComposeRule()

    private fun render(asset: String, expected: SignalQuality.Level) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val packets = context.assets.open("${EcgViewModel.REPLAY_DIR}/$asset.csv")
            .use { CaptureReplay.packets(it) }
        val pipeline = EcgPipeline()
        val until = (AT_SECONDS * EcgFilter.ECG_SAMPLE_RATE).toLong()
        packets.takeWhile { it.sampleOffset < until }.forEach { pipeline.onPacket(it.packet) }
        assertEquals("$asset at ${AT_SECONDS}s", expected, pipeline.signalQuality.level)

        compose.setContent {
            // The status line the ViewModel shows during a replay.
            MonitorContent("Replay $asset.csv", pipeline, tick = 0)
        }
        val dir = File(System.getProperty("screenshots.dir") ?: error("run via Gradle"), "before")
        compose.onRoot().captureRoboImage(File(dir, "roborazzi_$asset.png").path)
    }

    @Test fun dual03Good() = render("dual03_ring", SignalQuality.Level.GOOD)
    @Test fun dual02Fair() = render("dual02_ring", SignalQuality.Level.FAIR)
    @Test fun dual01Poor() = render("dual01_ring", SignalQuality.Level.POOR)

    companion object {
        // Matches the 20 s device screenshot. All three recordings sit in
        // their intended state here.
        const val AT_SECONDS = 20.0
    }
}
