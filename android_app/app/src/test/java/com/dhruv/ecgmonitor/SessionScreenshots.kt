package com.dhruv.ecgmonitor

import android.content.Context
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.util.TimeZone

/**
 * Session mode, its report and History, rendered from real recordings
 * replayed through EcgPipeline the way the app records a session. Same device
 * config as MonitorScreenshots (Galaxy A56). Images go to
 * screenshots/after/session_<state>_<orientation>.png.
 *
 * tb01 / tb02 are the two test-board captures (27 Oct 2026), the only ones of
 * ours longer than a session; most HRV measures are withheld on them, which is
 * the report working. mitdb103 is MIT-BIH development record 103, converted by
 * make_public_replay.py into the gitignored android_app/replay_public/; it is
 * the only replay on which every measure passes its gate, and its tests are
 * skipped when it is absent.
 */
abstract class SessionScreenshots {
    @get:Rule val compose = createComposeRule()

    abstract val orientation: String
    abstract val insetsPx: IntArray
    abstract val xdpi: Float
    abstract val ydpi: Float

    // Report dates are fixed, and printed in UTC, so renders repeat exactly.
    @Before fun utc() = TimeZone.setDefault(TimeZone.getTimeZone("UTC"))

    private fun assetPackets(asset: String): List<CaptureReplay.Packet>? {
        val context = ApplicationProvider.getApplicationContext<Context>()
        if ("$asset.csv" !in context.assets.list(EcgViewModel.REPLAY_DIR).orEmpty()) return null
        return context.assets.open("${EcgViewModel.REPLAY_DIR}/$asset.csv").use { CaptureReplay.packets(it) }
    }

    private fun packets(asset: String) = assetPackets(asset) ?: error("$asset not bundled")

    private fun geometry(): ScreenGeometry {
        val d = MonitorScreenshots.A56_DENSITY
        return ScreenGeometry(
            xdpi, ydpi,
            PaddingValues(
                start = (insetsPx[0] / d).dp, top = (insetsPx[1] / d).dp,
                end = (insetsPx[2] / d).dp, bottom = (insetsPx[3] / d).dp,
            ),
        )
    }

    private fun monitor(p: EcgPipeline, replay: String?, link: Link = Link.RECEIVING) = MonitorUiState(
        link = link, linkFix = null, dropped = false, status = "", replayFile = replay?.let { "$it.csv" },
        pipeline = p, tick = 0, gainMmPerMv = DEFAULT_GAIN_MM_PER_MV, showFiltered = true,
        researchMode = false, sampleRate = null,
    )

    private fun capture(name: String, scrollToEnd: String? = null, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent { MonitorTheme { Surface(Modifier.fillMaxSize()) { content() } } }
        compose.mainClock.advanceTimeBy(MonitorScreenshots.PING_PHASE_MS)
        val dir = File(System.getProperty("screenshots.dir") ?: error("run via Gradle"), "after")
        compose.onRoot().captureRoboImage(File(dir, "session_${name}_$orientation.png").path)
        if (scrollToEnd != null) {
            compose.mainClock.autoAdvance = true
            compose.onNodeWithTag(scrollToEnd).performScrollTo()
            compose.onRoot().captureRoboImage(File(dir, "session_${name}_end_$orientation.png").path)
        }
    }

    @Composable
    private fun session(phase: SessionPhase, p: EcgPipeline, replay: String?, historyCount: Int = 0, link: Link = Link.RECEIVING) {
        val rec = p.session
        val left = rec?.let { kotlin.math.ceil((1 - it.progress) * SessionConfig.DURATION_S).toInt() } ?: 0
        val s = SessionUiState(phase, monitor(p, replay, link), rec?.progress ?: 0.0, left, rec != null && rec.index >= rec.s1, historyCount)
        SessionScreen(s, SessionActions(), geometry())
    }

    private fun replayedTo(asset: String, seconds: Double): EcgPipeline {
        val p = EcgPipeline()
        packets(asset).takeWhile { it.sampleOffset < seconds * 256 }.forEach { p.onPacket(it.packet) }
        return p
    }

    // Fixed dates a day apart, from 3 Nov 2026 09:00 UTC.
    private fun day(i: Int) = 1_793_696_400_000L + i * 86_400_000L

    private fun reportOf(asset: String, startS: Double, dayIndex: Int): SessionReport {
        val (_, rec) = SessionReplay.run(packets(asset), startS)
        assertNotNull("$asset from $startS s: session did not finish", rec)
        return SessionReplay.report(rec!!, day(dayIndex), "$asset.csv")
    }

    // ------------------------------------------------------------- states

    @Test fun idle() {
        val p = replayedTo("dual03_ring", 20.0)
        capture("idle") { session(SessionPhase.Idle, p, "dual03_ring", historyCount = 4) }
    }

    @Test fun idleNotConnected() =
        capture("idle_not_connected") { session(SessionPhase.Idle, EcgPipeline(), null, link = Link.SCANNING) }

    // FAIR at 20 s (MonitorScreenshots.fair): the clock has not started.
    @Test fun waiting() {
        val p = replayedTo("dual02_ring", 20.0)
        assertEquals(SignalQuality.Level.FAIR, p.signalQuality.level)
        capture("waiting") { session(SessionPhase.Waiting, p, "dual02_ring") }
    }

    // Half-way through a session on tb02 that started at 20 s.
    @Test fun recording() {
        val (p, done) = SessionReplay.run(packets("tb02"), 20.0, untilS = 110.0)
        assertEquals(null, done)
        assertTrue(p.session!!.progress in 0.45..0.55)
        capture("recording") { session(SessionPhase.Recording(day(0), 0), p, "tb02") }
    }

    @Test fun reportTestBoard() {
        val r = reportOf("tb02", 20.0, 0)
        assertTrue("tb02 must withhold some measures", r.measures.values.any { it.value == null })
        capture("report_tb02", scrollToEnd = REPORT_END) { ReportScreen(r, geometry().insets, onDone = {}, onHistory = {}) }
    }

    @Test fun reportPublic() {
        assumeTrue("make_public_replay.py has not been run", assetPackets("mitdb103") != null)
        val r = reportOf("mitdb103", 20.0, 0)
        capture("report_mitdb103", scrollToEnd = REPORT_END) { ReportScreen(r, geometry().insets, onDone = {}, onHistory = {}) }
    }

    @Test fun reportFont130() = reportAtScale(1.3f)
    @Test fun reportFont200() = reportAtScale(2.0f)

    private fun reportAtScale(scale: Float) {
        RuntimeEnvironment.setFontScale(scale)
        val r = reportOf("tb02", 20.0, 0)
        capture("report_tb02_font${(scale * 100).toInt()}") { ReportScreen(r, geometry().insets, onDone = {}, onHistory = {}) }
    }

    // Real sessions from every long replay, a day apart.
    private fun history(): List<SessionReport> {
        val list = mutableListOf(
            reportOf("tb01", 20.0, 0), reportOf("tb02", 20.0, 1), reportOf("tb02", 100.0, 2),
        )
        if (assetPackets("mitdb103") != null) {
            list += reportOf("mitdb103", 10.0, 3); list += reportOf("mitdb103", 170.0, 4)
        }
        return list.sortedByDescending { it.startedAtMs }
    }

    @Test fun historyRmssd() {
        val h = history()
        capture("history_rmssd") { HistoryScreen(h, "rmssd", {}, {}, {}, geometry().insets) }
    }

    @Test fun historyHeartRate() {
        val h = history()
        capture("history_hr") { HistoryScreen(h, "hr", {}, {}, {}, geometry().insets) }
    }

    @Test fun historyEmpty() = capture("history_empty") { HistoryScreen(emptyList(), "rmssd", {}, {}, {}, geometry().insets) }

    // The main screen while a session records: the link carries the time left.
    @Test fun mainWhileRecording() {
        val (p, _) = SessionReplay.run(packets("tb02"), 20.0, untilS = 110.0)
        val s = monitor(p, "tb02").let {
            MonitorUiState(it.link, null, false, "", it.replayFile, p, 0, it.gainMmPerMv, true, false, null, sessionLabel = "Session 1:30")
        }
        capture("main_recording") { MainScreen(s, MonitorActions(), geometry()) }
    }
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w384dp-h832dp-port-450dpi")
class SessionScreenshotsPortrait : SessionScreenshots() {
    override val orientation = "portrait"
    override val insetsPx = intArrayOf(0, 101, 0, 135)
    override val xdpi = 386.3662f
    override val ydpi = 388.47058f
}

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w832dp-h384dp-land-450dpi")
class SessionScreenshotsLandscape : SessionScreenshots() {
    override val orientation = "landscape"
    override val insetsPx = intArrayOf(92, 84, 135, 0)
    override val xdpi = 388.47058f
    override val ydpi = 386.3662f
}
