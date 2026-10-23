package com.dhruv.ecgmonitor

import android.content.Context
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
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
 * Renders every main-screen state and Diagnostics from the bundled replay
 * captures at fixed points, so images are reproducible run to run. Each
 * replay case asserts the quality state it is meant to show.
 *
 * Device config is the test phone (Galaxy A56, SM-A566E): 1080 x 2340 px at
 * logical density 450. The app is edge-to-edge, so a render is the whole
 * screen; the phone's bar insets and physical DPI are passed in (measured,
 * screenshots/after/device_check.txt), so a render lines up with an
 * `adb screencap` and the grid is in real millimetres. Robolectric draws no
 * system bars, so those strips are empty.
 *
 * Images go to android_app/screenshots/after/, named <state>_<orientation>.
 * screenshots/before/ is the frozen pre-redesign baseline and is never written.
 */
abstract class MonitorScreenshots {
    @get:Rule val compose = createComposeRule()

    abstract val orientation: String
    abstract val insetsPx: IntArray        // left, top, right, bottom
    abstract val xdpi: Float
    abstract val ydpi: Float

    private fun replayed(asset: String, seconds: Double): EcgPipeline {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val packets = context.assets.open("${EcgViewModel.REPLAY_DIR}/$asset.csv").use { CaptureReplay.packets(it) }
        val p = EcgPipeline()
        val until = (seconds * EcgFilter.ECG_SAMPLE_RATE).toLong()
        packets.takeWhile { it.sampleOffset < until }.forEach { p.onPacket(it.packet) }
        return p
    }

    private fun state(
        p: EcgPipeline, link: Link, status: String, replay: String?, research: Boolean = false,
    ) = MonitorUiState(
        link = link, linkFix = null, status = status, replayFile = replay?.let { "$it.csv" },
        pipeline = p, tick = 0, gainMmPerMv = DEFAULT_GAIN_MM_PER_MV, showFiltered = true,
        researchMode = research,
        // Arrival rate is measured from wall-clock packet times, which a
        // render doesn't have; Diagnostics shows "not measured".
        sampleRate = null,
    )

    // diagnostics: also capture the page scrolled to its end, as <name>_end,
    // for what is below the fold (the Research section).
    private fun capture(name: String, s: MonitorUiState, diagnostics: Boolean = false) {
        val d = A56_DENSITY
        val geometry = ScreenGeometry(
            xdpi, ydpi,
            PaddingValues(
                start = (insetsPx[0] / d).dp, top = (insetsPx[1] / d).dp,
                end = (insetsPx[2] / d).dp, bottom = (insetsPx[3] / d).dp,
            ),
        )
        compose.setContent {
            MonitorTheme {
                Surface(Modifier.fillMaxSize()) {
                    if (diagnostics) DiagnosticsScreen(s, MonitorActions(), geometry)
                    else MainScreen(s, MonitorActions(), geometry)
                }
            }
        }
        val dir = File(System.getProperty("screenshots.dir") ?: error("run via Gradle"), "after")
        compose.onRoot().captureRoboImage(File(dir, "${name}_$orientation.png").path)
        if (diagnostics) {
            compose.onNodeWithTag(DIAGNOSTICS_END).performScrollTo()
            compose.onRoot().captureRoboImage(File(dir, "${name}_end_$orientation.png").path)
        }
    }

    private fun replayCase(name: String, asset: String, expected: SignalQuality.Level) {
        val p = replayed(asset, AT_SECONDS)
        assertEquals("$asset at ${AT_SECONDS}s", expected, p.signalQuality.level)
        capture(name, state(p, Link.RECEIVING, "Replay $asset.csv", asset))
    }

    @Test fun good() = replayCase("good", "dual03_ring", SignalQuality.Level.GOOD)
    @Test fun fair() = replayCase("fair", "dual02_ring", SignalQuality.Level.FAIR)
    @Test fun poor() = replayCase("poor", "dual01_ring", SignalQuality.Level.POOR)

    // First half second: receiving, but no verdict yet.
    @Test fun reading() {
        val p = replayed("dual03_ring", 0.5)
        assertEquals(false, p.qualityReady)
        capture("reading", state(p, Link.RECEIVING, "Replay dual03_ring.csv", "dual03_ring"))
    }

    @Test fun scanning() =
        capture("scanning", state(EcgPipeline(), Link.SCANNING, "Scanning for ESP32-ECG...", null))

    // The link dropped after 20 s of good data: nothing stale may show.
    @Test fun notConnected() =
        capture("not_connected", state(replayed("dual03_ring", AT_SECONDS), Link.NOT_CONNECTED, "Disconnected", null))

    @Test fun diagnostics() = capture(
        "diagnostics", state(replayed("dual03_ring", AT_SECONDS), Link.RECEIVING, "Replay dual03_ring.csv", "dual03_ring"),
        diagnostics = true,
    )

    @Test fun diagnosticsResearch() = capture(
        "diagnostics_research",
        state(replayed("dual03_ring", AT_SECONDS), Link.RECEIVING, "Replay dual03_ring.csv", "dual03_ring", research = true),
        diagnostics = true,
    )

    companion object {
        // All three recordings sit in their intended state here.
        const val AT_SECONDS = 20.0
        const val A56_DENSITY = 450 / 160f
    }
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w384dp-h832dp-port-450dpi")
class MonitorScreenshotsPortrait : MonitorScreenshots() {
    override val orientation = "portrait"
    override val insetsPx = intArrayOf(0, 101, 0, 135)
    override val xdpi = 386.3662f
    override val ydpi = 388.47058f
}

// Rotated 90 degrees: camera cutout on the left, nav bar on the right.
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w832dp-h384dp-land-450dpi")
class MonitorScreenshotsLandscape : MonitorScreenshots() {
    override val orientation = "landscape"
    override val insetsPx = intArrayOf(92, 84, 135, 0)
    override val xdpi = 388.47058f
    override val ydpi = 386.3662f
}
