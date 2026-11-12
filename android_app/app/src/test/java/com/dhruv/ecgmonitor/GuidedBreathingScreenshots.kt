package com.dhruv.ecgmonitor

import android.content.Context
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * The guided-breathing screen from real recordings replayed through
 * EcgPipeline: tb02 (the test board, 27 Oct 2026), with the exercise started
 * at 110 s so the window at 200 s holds 90 s of it. These are the test
 * subject breathing normally, not paced, so the curve does not follow the
 * bands; the renders show the screen, not an effect.
 * Images: screenshots/after/breathing_<state>_<orientation>.png.
 */
abstract class GuidedBreathingScreenshots {
    @get:Rule val compose = createComposeRule()
    abstract val orientation: String
    abstract val insetsPx: IntArray
    abstract val xdpi: Float
    abstract val ydpi: Float

    private fun replayed(asset: String, seconds: Double): EcgPipeline {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val packets = context.assets.open("${EcgViewModel.REPLAY_DIR}/$asset.csv").use { CaptureReplay.packets(it) }
        val p = EcgPipeline()
        packets.takeWhile { it.sampleOffset < seconds * 256 }.forEach { p.onPacket(it.packet) }
        return p
    }

    private fun capture(name: String, phase: BreathingPhase, elapsed: Double, p: EcgPipeline, replay: String?, link: Link = Link.RECEIVING) {
        val d = MonitorScreenshots.A56_DENSITY
        val geometry = ScreenGeometry(
            xdpi, ydpi,
            PaddingValues((insetsPx[0] / d).dp, (insetsPx[1] / d).dp, (insetsPx[2] / d).dp, (insetsPx[3] / d).dp),
        )
        val monitor = MonitorUiState(
            link, null, false, "", replay?.let { "$it.csv" }, p, 0, DEFAULT_GAIN_MM_PER_MV, true, false, null,
        )
        val snap = if (p.live.index > 0) p.live.snapshot() else null
        compose.mainClock.autoAdvance = false
        compose.setContent {
            MonitorTheme { Surface(Modifier.fillMaxSize()) {
                GuidedBreathingScreen(BreathingUiState(phase, elapsed, snap, monitor), BreathingActions(), geometry)
            } }
        }
        compose.mainClock.advanceTimeBy(100)
        val dir = File(System.getProperty("screenshots.dir") ?: error("run via Gradle"), "after")
        compose.onRoot().captureRoboImage(File(dir, "breathing_${name}_$orientation.png").path)
    }

    @Test fun idle() = capture("idle", BreathingPhase.Idle, 0.0, replayed("tb02", 60.0), "tb02")

    @Test fun idleNotConnected() = capture("idle_not_connected", BreathingPhase.Idle, 0.0, EcgPipeline(), null, Link.SCANNING)

    // 90 s in, 2 s into an inhale (breath 10): the live window is all exercise.
    @Test fun running() {
        val p = replayed("tb02", 200.0)
        capture("running", BreathingPhase.Running(0, (110 * 256).toLong()), 92.0, p, "tb02")
    }

    // Only 25 s in: RMSSD still withheld, with its reason.
    @Test fun runningEarly() {
        val p = replayed("tb02", 135.0)
        capture("running_early", BreathingPhase.Running(0, (110 * 256).toLong()), 27.5, p, "tb02")
    }

    @Test fun done() {
        val p = replayed("tb02", 290.0)
        val last = p.live.snapshot()
        assertNotNull(last.rmssd)
        capture("done", BreathingPhase.Done(last, (110 * 256).toLong()), 180.0, p, "tb02")
    }

    @Test fun runningFont200() {
        RuntimeEnvironment.setFontScale(2.0f)
        capture("running_font200", BreathingPhase.Running(0, (110 * 256).toLong()), 92.0, replayed("tb02", 200.0), "tb02")
    }
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w384dp-h832dp-port-450dpi")
class GuidedBreathingScreenshotsPortrait : GuidedBreathingScreenshots() {
    override val orientation = "portrait"
    override val insetsPx = intArrayOf(0, 101, 0, 135)
    override val xdpi = 386.3662f
    override val ydpi = 388.47058f
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w832dp-h384dp-land-450dpi")
class GuidedBreathingScreenshotsLandscape : GuidedBreathingScreenshots() {
    override val orientation = "landscape"
    override val insetsPx = intArrayOf(92, 84, 135, 0)
    override val xdpi = 388.47058f
    override val ydpi = 386.3662f
}
