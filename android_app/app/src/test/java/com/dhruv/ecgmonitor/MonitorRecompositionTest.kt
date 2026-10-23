package com.dhruv.ecgmonitor

import android.content.Context
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

// One composition fed a live pipeline, the way the app runs it. Screenshot
// tests each render a first composition, so they can't see a part of the
// screen that stops updating; this can. Every pipeline-derived element of
// the heart-rate block must follow the stream.
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34], qualifiers = "w384dp-h832dp-port-450dpi")
class MonitorRecompositionTest {
    @get:Rule val compose = createComposeRule()

    @Test fun heartRateBlockFollowsTheStream() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val packets = context.assets.open("${EcgViewModel.REPLAY_DIR}/dual03_ring.csv").use { CaptureReplay.packets(it) }
        val p = EcgPipeline()
        var tick by mutableIntStateOf(0)
        compose.setContent {
            MonitorTheme {
                MainScreen(
                    MonitorUiState(
                        Link.RECEIVING, null, "Replay dual03_ring.csv", "dual03_ring.csv", p, tick,
                        DEFAULT_GAIN_MM_PER_MV, showFiltered = true, researchMode = false, sampleRate = null,
                    ),
                    MonitorActions(), ScreenGeometry(386.3662f, 388.47058f, PaddingValues()),
                )
            }
        }
        fun feedUntil(seconds: Double) {
            packets.filter { it.sampleOffset in (p.sweepFiltered.total until (seconds * 256).toLong()) }
                .forEach { p.onPacket(it.packet) }
            tick++
            compose.waitForIdle()
        }
        feedUntil(0.5)
        compose.onNodeWithText("Checking signal").assertIsDisplayed()
        feedUntil(20.0)
        compose.onNodeWithText("Good signal").assertIsDisplayed()
        compose.onNodeWithText("${p.heartRate!!.let { kotlin.math.round(it).toInt() }}").assertIsDisplayed()
    }
}
