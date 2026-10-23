package com.dhruv.ecgmonitor

import android.animation.ValueAnimator
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt

// Where the data is coming from, as the main screen describes it.
enum class Link { SCANNING, RECEIVING, NOT_CONNECTED, REPLAY_FINISHED }

// What the heart-rate area says. Decided here, away from layout, so the
// rules are unit-tested (HeadlineTest).
sealed interface Headline {
    data class Rate(val bpm: Int) : Headline
    // Heart rate withheld: a muted dash, and the likely cause with its fix.
    data class Hidden(val cause: String) : Headline
    // No data to judge: the message takes the number's place. `alert` only
    // when a live stream was lost this session, never before the first one.
    data class NoData(val message: String, val fix: String?, val alert: Boolean = false) : Headline
}

private const val RING_FIX = "Turn the ring on and keep it near the phone"

fun headline(
    link: Link,
    linkFix: String?,
    dropped: Boolean,
    qualityReady: Boolean,
    level: SignalQuality.Level,
    heartRate: Double?,
    mainsShare: Double,
): Headline = when (link) {
    Link.SCANNING -> Headline.NoData("Scanning for ring…", RING_FIX)
    Link.NOT_CONNECTED -> Headline.NoData("Ring not connected", linkFix ?: RING_FIX, alert = dropped)
    Link.REPLAY_FINISHED -> Headline.NoData("Replay finished", null)
    Link.RECEIVING -> when {
        !qualityReady -> Headline.Hidden("Hold still for a few seconds")
        // Only GOOD shows a number: replaying the gate (sqi_replay.py) found
        // a chest channel at FAIR 85% of the time detecting 241 beats against
        // the finger's 186, so FAIR lets wrong rates through.
        level == SignalQuality.Level.GOOD ->
            if (heartRate != null) Headline.Rate(heartRate.roundToInt()) else Headline.Hidden("Measuring")
        // Mains on the raw input points at the reference electrode before motion.
        mainsShare >= MAINS_REFERENCE_SUSPECT -> Headline.Hidden("Check the reference electrode")
        level == SignalQuality.Level.FAIR -> Headline.Hidden("Hold still")
        else -> Headline.Hidden("Press your finger fully on the electrode")
    }
}

// Everything the two screens read. Rebuilt on every recomposition from the
// ViewModel, or built directly by the screenshot tests.
class MonitorUiState(
    val link: Link,
    val linkFix: String?,
    val dropped: Boolean,
    val status: String,
    val replayFile: String?,
    val pipeline: EcgPipeline,
    val tick: Int,
    val gainMmPerMv: Int,
    val showFiltered: Boolean,
    val researchMode: Boolean,
    val sampleRate: Double?,
) {
    val headline: Headline
        get() = pipeline.let {
            headline(link, linkFix, dropped, it.qualityReady, it.signalQuality.level, it.heartRate, it.mainsShare)
        }
}

class MonitorActions(
    val onCycleGain: () -> Unit = {},
    val onShowFiltered: (Boolean) -> Unit = {},
    val onResearchMode: (Boolean) -> Unit = {},
    val onOpenDiagnostics: () -> Unit = {},
    val onBack: () -> Unit = {},
)

// Physical DPI for the millimetre grid, and the system-bar insets to keep
// content clear of.
class ScreenGeometry(val xdpi: Float, val ydpi: Float, val insets: PaddingValues)

private val NumberStyle = TextStyle(
    fontFamily = PlexSansCondensed, fontWeight = FontWeight.Medium, fontSize = 80.sp,
    lineHeight = 80.sp, fontFeatureSettings = TABULAR,
    lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Bottom, LineHeightStyle.Trim.Both),
)
private val NUMBER_SLOT = 84.dp
private val QUALITY_SLOT = 28.dp
private val CAUSE_SLOT = 22.dp

// ---------------------------------------------------------------- main screen

@Composable
fun MainScreen(state: MonitorUiState, actions: MonitorActions, geometry: ScreenGeometry) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        if (maxWidth > maxHeight) MainLandscape(state, actions, geometry)
        else MainPortrait(state, actions, geometry)
    }
}

@Composable
private fun MainPortrait(state: MonitorUiState, actions: MonitorActions, geometry: ScreenGeometry) {
    val insets = geometry.insets
    Column(Modifier.fillMaxSize()) {
        HeartRateBlock(
            state, causeLines = 1,
            modifier = Modifier
                .padding(top = insets.calculateTopPadding())
                .padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 4.dp),
        )
        // Air between the header and the paper, so the grid doesn't crowd the cause line.
        Spacer(Modifier.height(12.dp))
        Trace(state, geometry, Modifier.fillMaxWidth().weight(1f))
        Row(
            Modifier.fillMaxWidth()
                .padding(bottom = insets.calculateBottomPadding())
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TraceCaption(state.gainMmPerMv, raw = !state.showFiltered, onCycleGain = actions.onCycleGain)
            Spacer(Modifier.weight(1f))
            DiagnosticsLink(actions.onOpenDiagnostics)
        }
    }
}

@Composable
private fun MainLandscape(state: MonitorUiState, actions: MonitorActions, geometry: ScreenGeometry) {
    val insets = geometry.insets
    val dir = LocalLayoutDirection.current
    Row(
        Modifier.fillMaxSize().padding(
            start = insets.calculateStartPadding(dir), top = insets.calculateTopPadding(),
            end = insets.calculateEndPadding(dir), bottom = insets.calculateBottomPadding(),
        )
    ) {
        Column(Modifier.width(SIDE_COLUMN).fillMaxHeight().padding(start = 16.dp, end = 12.dp, top = 8.dp)) {
            HeartRateBlock(state, causeLines = 3)
            Spacer(Modifier.weight(1f))
            DiagnosticsLink(actions.onOpenDiagnostics)
        }
        Column(Modifier.weight(1f).fillMaxHeight()) {
            Trace(state, geometry, Modifier.fillMaxWidth().weight(1f))
            TraceCaption(
                state.gainMmPerMv, raw = !state.showFiltered, onCycleGain = actions.onCycleGain,
                modifier = Modifier.padding(horizontal = 12.dp),
            )
        }
    }
}

private val SIDE_COLUMN = 184.dp

@Composable
private fun Trace(state: MonitorUiState, geometry: ScreenGeometry, modifier: Modifier) {
    val p = state.pipeline
    EcgTrace(
        buffer = if (state.showFiltered) p.sweepFiltered else p.sweepRaw,
        tick = state.tick, showTrace = state.link == Link.RECEIVING, mmPerMv = state.gainMmPerMv,
        xdpi = geometry.xdpi, ydpi = geometry.ydpi, modifier = modifier,
    )
}

// Heart rate, quality and the cause line, in fixed-height slots so the block
// is the same size whatever it says and the trace below never moves.
@Composable
private fun HeartRateBlock(state: MonitorUiState, causeLines: Int, modifier: Modifier = Modifier) {
    val headline = state.headline
    Column(modifier) {
        state.replayFile?.let { ReplayTag(it) }
        Box(Modifier.height(NUMBER_SLOT).fillMaxWidth(), contentAlignment = Alignment.BottomStart) {
            when (headline) {
                is Headline.Rate -> Number("${headline.bpm}", MonitorColors.Text)
                // The dash alone: next to it, "bpm" read as a separate label.
                is Headline.Hidden -> Text("—", style = NumberStyle, color = MonitorColors.TextMuted)
                is Headline.NoData -> Text(
                    headline.message,
                    style = NumberStyle.copy(fontSize = 30.sp, lineHeight = 34.sp),
                    // Losing the ring mid-session is the one alert here.
                    color = if (headline.alert) MonitorColors.Alert else MonitorColors.Text,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
            }
        }
        Box(Modifier.height(QUALITY_SLOT), contentAlignment = Alignment.CenterStart) {
            when (state.link) {
                Link.RECEIVING -> QualityRow(state.pipeline.qualityReady, state.pipeline.signalQuality.level)
                Link.SCANNING -> ScanningPing()
                else -> {}
            }
        }
        val cause = when (headline) {
            is Headline.Hidden -> headline.cause
            is Headline.NoData -> headline.fix
            is Headline.Rate -> null
        }
        Box(Modifier.height(CAUSE_SLOT * causeLines), contentAlignment = Alignment.TopStart) {
            if (cause != null) Text(
                cause, style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted,
                maxLines = causeLines, overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun Number(text: String, color: androidx.compose.ui.graphics.Color) {
    Row {
        Text(text, style = NumberStyle, color = color, modifier = Modifier.alignByBaseline())
        Text(
            " bpm", style = MaterialTheme.typography.titleMedium, color = MonitorColors.TextMuted,
            modifier = Modifier.alignByBaseline(),
        )
    }
}

// The quality word and a three-bar glyph. The bar count carries the state as
// a shape, so it never rests on colour. Takes values, not the pipeline: the
// pipeline is the same instance every frame, so Compose would skip this and
// leave it frozen on its first state (seen on the phone: "98 bpm" beside
// "Checking signal"). Pinned by MonitorRecompositionTest.
@Composable
private fun QualityRow(ready: Boolean, level: SignalQuality.Level) {
    val (word, bars) = if (!ready) "Checking signal" to 0 else when (level) {
        SignalQuality.Level.GOOD -> "Good signal" to 3
        SignalQuality.Level.FAIR -> "Fair signal" to 2
        SignalQuality.Level.POOR -> "Poor signal" to 1
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        QualityBars(bars, Modifier.semantics { contentDescription = "$bars of 3 bars" })
        Spacer(Modifier.width(8.dp))
        Text(word, style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text)
    }
}

@Composable
private fun QualityBars(filled: Int, modifier: Modifier = Modifier) {
    Canvas(modifier.size(width = 18.dp, height = 14.dp)) {
        val w = 4.dp.toPx(); val gap = 3.dp.toPx(); val r = CornerRadius(1.dp.toPx())
        for (i in 0 until 3) {
            val h = size.height * (i + 1) / 3
            val topLeft = Offset(i * (w + gap), size.height - h)
            if (i < filled) {
                drawRoundRect(MonitorColors.Text, topLeft, Size(w, h), r)
            } else {
                val s = 1.dp.toPx()
                drawRoundRect(
                    MonitorColors.TextMuted, topLeft + Offset(s / 2, s / 2), Size(w - s, h - s), r,
                    style = Stroke(s),
                )
            }
        }
    }
}

// A slow expanding ring while scanning: the app is working, quietly. Still
// (one ring at rest) when the system has animations turned off.
@Composable
private fun ScanningPing() {
    val animate = remember { ValueAnimator.areAnimatorsEnabled() }
    val phase = if (animate) {
        rememberInfiniteTransition(label = "scan").animateFloat(
            0f, 1f, infiniteRepeatable(tween(PING_MS, easing = LinearEasing)), label = "ping",
        ).value
    } else 0.6f
    Canvas(Modifier.size(18.dp).semantics { contentDescription = "Searching" }) {
        val r = size.minDimension / 2
        drawCircle(MonitorColors.TextMuted, radius = 2.dp.toPx())
        drawCircle(
            MonitorColors.TextMuted.copy(alpha = 1f - phase), radius = 2.dp.toPx() + (r - 2.dp.toPx()) * phase,
            style = Stroke(1.dp.toPx()),
        )
    }
}

private const val PING_MS = 1800

// Permanent in replay, so a recording is never mistaken for live data.
@Composable
private fun ReplayTag(file: String) {
    Text(
        // ".csv" says nothing; dropping it keeps the name whole in landscape.
        "REPLAY · ${file.removeSuffix(".csv")}",
        style = MaterialTheme.typography.labelMedium, color = MonitorColors.Text,
        modifier = Modifier
            .padding(bottom = 4.dp)
            .border(1.dp, MonitorColors.TextMuted, RoundedCornerShape(3.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
private fun DiagnosticsLink(onClick: () -> Unit) {
    Text(
        "Diagnostics ›",
        style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
        modifier = Modifier
            .minimumInteractiveComponentSize()
            .clickable(role = Role.Button, onClick = onClick),
    )
}

// ---------------------------------------------------------------- diagnostics

@Composable
fun DiagnosticsScreen(state: MonitorUiState, actions: MonitorActions, geometry: ScreenGeometry) {
    val p = state.pipeline
    val dir = LocalLayoutDirection.current
    val insets = geometry.insets
    Column(
        Modifier.fillMaxSize()
            .padding(
                start = insets.calculateStartPadding(dir), top = insets.calculateTopPadding(),
                end = insets.calculateEndPadding(dir), bottom = insets.calculateBottomPadding(),
            )
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 8.dp)
            // Keeps label and value close, and notes short, in landscape.
            .widthIn(max = 560.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Diagnostics", style = MaterialTheme.typography.titleLarge, color = MonitorColors.Text)
            Spacer(Modifier.weight(1f))
            Text(
                "Back", style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted,
                modifier = Modifier.minimumInteractiveComponentSize().clickable(role = Role.Button, onClick = actions.onBack),
            )
        }

        Section("Connection")
        Field("Source", state.replayFile?.let { "Replay of $it" } ?: "Bluetooth, ESP32-ECG")
        // The client's own messages ("Found …, connecting…"); in a replay they
        // only repeat the source.
        if (state.replayFile == null) Field("Status", state.status.replace("...", "…"))
        Field("Stream", when (state.link) {
            Link.SCANNING -> "Scanning"
            Link.RECEIVING -> "Receiving"
            Link.NOT_CONNECTED -> "Not connected"
            Link.REPLAY_FINISHED -> "Replay finished"
        })

        Section("Packets")
        val total = p.packetsSeen + p.packetsLost
        Field("Received", "${p.packetsSeen}")
        Field("Lost", if (total == 0) "none yet" else "${p.packetsLost} (%.2f%%)".format(100.0 * p.packetsLost / total))
        Field("Samples skipped", "${p.samplesSkipped}")
        Field("Last packet", if (p.lastSeq < 0) "none yet" else "seq ${p.lastSeq}, ${p.lastCount} samples")
        Field("Sample rate, last 5 s", state.sampleRate?.let { "%.1f SPS".format(it) } ?: "not measured")

        Section("Signal quality", "Thresholds are from published convention, not calibrated on our hardware.")
        val sq = p.signalQuality
        if (p.qualityReady) {
            Field("Verdict", sq.level.name.lowercase().replaceFirstChar { it.uppercase() })
            Field("kSQI, kurtosis", "%.1f".format(sq.kSqi))
            Field("pSQI, 5–15 Hz share", "%.2f".format(sq.pSqi))
            Field("Mains share, raw", "%.1f%%".format(100 * p.mainsShare))
        } else {
            Field("Verdict", "waiting for 1 s of data")
        }

        Section("Detector and filter")
        Field("Beats in RR history", "${p.detector.beatCount}")
        Field("Filter", "0.5 Hz high-pass, 50/100 Hz notch, 40 Hz low-pass")
        Field("Delay", "causal, %.1f ms".format(p.filter.groupDelayMs))

        Section("Trace", "Scale is nominal: 1 mV = ${"%.2f".format(NOMINAL_CODES_PER_MV)} codes at gain 20 (datasheet check #23).")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(state.showFiltered, { actions.onShowFiltered(true) }, label = { Text("Filtered") })
            FilterChip(!state.showFiltered, { actions.onShowFiltered(false) }, label = { Text("Raw") })
        }

        Section("Research")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Research mode", style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text)
                Text(
                    "Shows measurements that have not been validated.",
                    style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
                )
            }
            Switch(
                checked = state.researchMode, onCheckedChange = actions.onResearchMode,
                colors = SwitchDefaults.colors(
                    checkedThumbColor = MonitorColors.Black, checkedTrackColor = MonitorColors.Text,
                    uncheckedThumbColor = MonitorColors.TextMuted, uncheckedTrackColor = MonitorColors.Black,
                    uncheckedBorderColor = MonitorColors.TextMuted,
                ),
            )
        }
        if (state.researchMode) {
            val rmssd = p.rmssdMs
            Field(
                "RMSSD, unvalidated",
                if (rmssd == null) "needs ${BeatDetector.MIN_BEATS_FOR_HRV} beats"
                else "%.0f ms from %d beats".format(rmssd, p.detector.beatCount),
            )
        }
        Spacer(Modifier.height(16.dp).testTag(DIAGNOSTICS_END))
    }
}

const val DIAGNOSTICS_END = "diagnostics_end"

@Composable
private fun Section(title: String, note: String? = null) {
    Spacer(Modifier.height(20.dp))
    HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
    Spacer(Modifier.height(12.dp))
    Text(title, style = MaterialTheme.typography.titleSmall, color = MonitorColors.Text)
    if (note != null) Text(note, style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted)
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun Field(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted, modifier = Modifier.weight(0.45f))
        Text(value, style = MaterialTheme.typography.bodyMedium, color = MonitorColors.Text, modifier = Modifier.weight(0.55f))
    }
}
