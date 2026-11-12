package com.dhruv.ecgmonitor

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

// Session mode: a fixed-length recording, then a report of every measure the
// algorithms/ package defines, each shown only when it meets its own minimum
// window and coverage rule, otherwise "—" and the rule's reason, verbatim.

/** Everything the Session screen reads, as values (see android_app/CLAUDE.md:
 *  never hand the pipeline to a small composable). */
class SessionUiState(
    val phase: SessionPhase,
    val monitor: MonitorUiState,
    /** 0..1 through the recording. */
    val progress: Double,
    val secondsLeft: Int,
    /** Recorded part over, waiting for the detector's tail. */
    val finishing: Boolean,
    val historyCount: Int,
)

class SessionActions(
    val onStart: () -> Unit = {},
    val onCancel: () -> Unit = {},
    val onDone: () -> Unit = {},
    val onHistory: () -> Unit = {},
    val onBack: () -> Unit = {},
    val onDelete: (Long) -> Unit = {},
    val onCycleGain: () -> Unit = {},
)

/** Report rows: key, label, unit as shown, decimals, and the noun for nUsed. */
internal class MeasureSpec(val key: String, val label: String, val unit: String, val decimals: Int, val noun: String)

internal val REPORT_SECTIONS: List<Pair<String, List<MeasureSpec>>> = listOf(
    "Rates" to listOf(
        MeasureSpec("hr", "Heart rate", "bpm", 0, "beat-to-beat intervals"),
        MeasureSpec("br", "Breathing rate", "/min", 1, "windows"),
    ),
    "Variability" to listOf(
        MeasureSpec("rmssd", "RMSSD", "ms", 0, "successive differences"),
        MeasureSpec("sdnn", "SDNN", "ms", 0, "NN intervals"),
        MeasureSpec("pnn50", "pNN50", "%", 1, "successive differences"),
    ),
    "Poincaré" to listOf(
        MeasureSpec("sd1", "SD1", "ms", 0, "successive pairs"),
        MeasureSpec("sd2", "SD2", "ms", 0, "successive pairs"),
    ),
    "Frequency" to listOf(
        MeasureSpec("lf", "LF power", "ms²", 0, "NN intervals"),
        MeasureSpec("hf", "HF power", "ms²", 0, "NN intervals"),
        MeasureSpec("lf_hf", "LF/HF", "", 2, "NN intervals"),
    ),
    "Fractal" to listOf(
        MeasureSpec("dfa_alpha1", "DFA α1", "", 2, "NN intervals in runs"),
    ),
)
internal val ALL_SPECS = REPORT_SECTIONS.flatMap { it.second }

/** Rhythm check, ectopic count, motion and arousal (PendingSlots) stay off
 *  the report until each has a validated algorithm feeding it. */
const val PENDING_SLOTS_VISIBLE = false

private const val LF_HF_CAVEAT =
    "LF/HF is the ratio of two frequency bands. It is not a measure of sympathetic–vagal balance."

const val REPORT_END = "report_end"

internal fun formatValue(v: Double, decimals: Int): String = "%.${decimals}f".format(Locale.ROOT, v)

private fun clock(seconds: Int) = "%d:%02d".format(Locale.ROOT, seconds / 60, seconds % 60)

internal fun reportDate(ms: Long): String = SimpleDateFormat("d MMM yyyy, HH:mm", Locale.UK).format(Date(ms))

// ---------------------------------------------------------------- scaffold

@Composable
private fun Page(
    title: String, insets: PaddingValues, right: String?, onRight: () -> Unit,
    scroll: Boolean = true, content: @Composable ColumnScope.() -> Unit,
) {
    val dir = LocalLayoutDirection.current
    Column(
        Modifier.fillMaxSize().padding(
            start = insets.calculateStartPadding(dir), top = insets.calculateTopPadding(),
            end = insets.calculateEndPadding(dir), bottom = insets.calculateBottomPadding(),
        )
    ) {
        PageHeader(title, right, onRight)
        val body = Modifier.fillMaxWidth().weight(1f)
        Column(
            (if (scroll) body.verticalScroll(rememberScrollState()) else body)
                .padding(horizontal = 20.dp)
                .widthIn(max = 600.dp),
            content = content,
        )
    }
}

@Composable
private fun PageHeader(title: String, right: String?, onRight: () -> Unit) {
    Row(Modifier.padding(start = 20.dp, end = 20.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = MaterialTheme.typography.titleLarge, color = MonitorColors.Text, modifier = Modifier.weight(1f))
        if (right != null) Text(
            right, style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted,
            modifier = Modifier.minimumInteractiveComponentSize().clickable(role = Role.Button, onClick = onRight),
        )
    }
}

@Composable
private fun PlainButton(text: String, onClick: () -> Unit, enabled: Boolean = true, modifier: Modifier = Modifier) {
    OutlinedButton(
        onClick, enabled = enabled, modifier = modifier.heightIn(min = 52.dp),
        shape = RoundedCornerShape(6.dp),
        border = BorderStroke(1.dp, if (enabled) MonitorColors.Text else MonitorColors.GridMajor),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = MonitorColors.Text, disabledContentColor = MonitorColors.TextMuted,
        ),
    ) { Text(text, style = MaterialTheme.typography.titleMedium) }
}

@Composable
private fun Muted(text: String, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) = Text(
    text, style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted, modifier = modifier,
    maxLines = maxLines, overflow = TextOverflow.Ellipsis,
)

// ----------------------------------------------------------- session screen

@Composable
fun SessionScreen(state: SessionUiState, actions: SessionActions, geometry: ScreenGeometry) {
    when (val ph = state.phase) {
        is SessionPhase.Done -> ReportScreen(ph.report, geometry.insets, onDone = actions.onDone, onHistory = actions.onHistory)
        is SessionPhase.Recording -> RecordingScreen(state, actions, geometry)
        else -> Page("Session", geometry.insets, "Back", actions.onBack) {
            val m = state.monitor
            m.replayFile?.let { Spacer(Modifier.height(8.dp)); ReplayTag(it) }
            Spacer(Modifier.height(16.dp))
            if (ph == SessionPhase.Waiting) {
                Text("Waiting for a good signal", style = NoDataStyle, color = MonitorColors.Text)
                Spacer(Modifier.height(8.dp))
                val cause = when (val h = m.headline) {
                    is Headline.Hidden -> h.cause
                    is Headline.NoData -> h.message
                    is Headline.Rate -> "Starting"
                }
                Muted("Recording starts by itself once the heart rate shows. $cause.")
                Spacer(Modifier.height(24.dp))
                PlainButton("Cancel", actions.onCancel, modifier = Modifier.fillMaxWidth())
            } else {
                Text(
                    "${clock(SessionConfig.DURATION_S.toInt())} sitting still",
                    style = NoDataStyle, color = MonitorColors.Text,
                )
                Spacer(Modifier.height(8.dp))
                Muted(
                    "Rest your hand with the finger on the electrode and breathe normally. " +
                        "The report comes when the time is up."
                )
                Spacer(Modifier.height(24.dp))
                val receiving = m.link == Link.RECEIVING
                PlainButton("Start", actions.onStart, enabled = receiving, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(8.dp))
                Muted(if (receiving) "It waits for a good signal before the clock starts." else "Connect the ring first.")
            }
            Spacer(Modifier.height(32.dp))
            HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
            Row(
                Modifier.fillMaxWidth().minimumInteractiveComponentSize()
                    .clickable(role = Role.Button, onClick = actions.onHistory),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("History", style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text, modifier = Modifier.weight(1f))
                Muted(
                    when (state.historyCount) { 0 -> "no sessions yet ›"; 1 -> "1 session ›"; else -> "${state.historyCount} sessions ›" },
                )
            }
        }
    }
}

// Portrait: header and status in the page margins, the strip edge to edge
// below them. Landscape: status in a side column and the strip full height,
// as on the main screen (android_app/CLAUDE.md), so the 1 mV pulse fits.
@Composable
private fun RecordingScreen(state: SessionUiState, actions: SessionActions, geometry: ScreenGeometry) {
    val m = state.monitor
    val insets = geometry.insets
    val dir = LocalLayoutDirection.current
    val trace = @Composable { mod: Modifier ->
        EcgTrace(
            buffer = if (m.showFiltered) m.pipeline.sweepFiltered else m.pipeline.sweepRaw,
            tick = m.tick, showTrace = m.link == Link.RECEIVING, mmPerMv = m.gainMmPerMv,
            xdpi = geometry.xdpi, ydpi = geometry.ydpi, modifier = mod,
        )
    }
    BoxWithConstraints(
        Modifier.fillMaxSize().padding(
            start = insets.calculateStartPadding(dir), top = insets.calculateTopPadding(),
            end = insets.calculateEndPadding(dir), bottom = insets.calculateBottomPadding(),
        )
    ) {
        if (maxWidth > maxHeight) Row(Modifier.fillMaxSize()) {
            Column(Modifier.width(240.dp).fillMaxHeight()) {
                PageHeader("Session", "Cancel", actions.onCancel)
                Column(Modifier.padding(horizontal = 20.dp)) { RecordingStatus(state, NoDataStyle) }
            }
            Column(Modifier.weight(1f).fillMaxHeight()) {
                trace(Modifier.fillMaxWidth().weight(1f))
                TraceCaption(m.gainMmPerMv, raw = !m.showFiltered, onCycleGain = actions.onCycleGain, modifier = Modifier.padding(horizontal = 12.dp))
            }
        } else Column(Modifier.fillMaxSize()) {
            PageHeader("Session", "Cancel", actions.onCancel)
            Column(Modifier.padding(horizontal = 20.dp)) { RecordingStatus(state, NumberStyle) }
            Spacer(Modifier.height(16.dp))
            trace(Modifier.fillMaxWidth().weight(1f))
            TraceCaption(m.gainMmPerMv, raw = !m.showFiltered, onCycleGain = actions.onCycleGain, modifier = Modifier.padding(horizontal = 20.dp))
        }
    }
}

@Composable
private fun RecordingStatus(state: SessionUiState, clockStyle: androidx.compose.ui.text.TextStyle) {
    val m = state.monitor
    m.replayFile?.let { Spacer(Modifier.height(4.dp)); ReplayTag(it) }
    Row(verticalAlignment = Alignment.Bottom) {
        Text(clock(state.secondsLeft), style = clockStyle, color = MonitorColors.Text, modifier = Modifier.alignByBaseline())
        Text(
            if (state.finishing) " finishing…" else " left", style = MaterialTheme.typography.titleMedium,
            color = MonitorColors.TextMuted, modifier = Modifier.alignByBaseline(),
        )
    }
    Spacer(Modifier.height(8.dp))
    ProgressLine(state.progress)
    Spacer(Modifier.height(10.dp))
    // The live heart rate under the main screen's rule: only on GOOD.
    val (rate, note) = when (val h = m.headline) {
        is Headline.Rate -> "${h.bpm} bpm" to null
        is Headline.Hidden -> "—" to h.cause
        is Headline.NoData -> "—" to h.message
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(rate, style = MaterialTheme.typography.titleMedium, color = MonitorColors.Text)
        Spacer(Modifier.width(12.dp))
        if (m.link == Link.RECEIVING) QualityRow(m.pipeline.qualityReady, m.pipeline.signalQuality.level)
    }
    Muted(note ?: "Keep still until the time is up.", maxLines = 3)
}

@Composable
private fun ProgressLine(progress: Double) {
    Canvas(
        Modifier.fillMaxWidth().height(6.dp)
            .semantics { contentDescription = "${(progress * 100).roundToInt()}% recorded" }
    ) {
        val y = size.height / 2
        drawLine(MonitorColors.GridMajor, Offset(0f, y), Offset(size.width, y), strokeWidth = 2.dp.toPx())
        drawLine(
            MonitorColors.Text, Offset(0f, y), Offset(size.width * progress.toFloat(), y),
            strokeWidth = 2.dp.toPx(),
        )
    }
}

// ------------------------------------------------------------------ report

@Composable
fun ReportScreen(
    report: SessionReport, insets: PaddingValues, onDone: () -> Unit, onHistory: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null, title: String = "Session report", doneLabel: String = "Done",
) {
    Page(title, insets, doneLabel, onDone) {
        Spacer(Modifier.height(4.dp))
        Text(
            "${reportDate(report.startedAtMs)} · ${clock(report.durationS.roundToInt())}",
            style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text,
        )
        report.replayFile?.let { Spacer(Modifier.height(6.dp)); ReplayTag(it) }
        Spacer(Modifier.height(6.dp))
        Muted(summaryLine(report))
        if (report.endedEarly) {
            Spacer(Modifier.height(4.dp))
            Text("Ended early: the stream stopped.", style = MaterialTheme.typography.bodyMedium, color = MonitorColors.Text)
        }
        for ((title, specs) in REPORT_SECTIONS) {
            ReportSection(title)
            for (spec in specs) {
                val m = report.measures[spec.key]
                MeasureRow(spec, m)
            }
            if (title == "Frequency") {
                Spacer(Modifier.height(2.dp))
                Text(LF_HF_CAVEAT, style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted)
            }
        }
        @Suppress("KotlinConstantConditions")
        if (PENDING_SLOTS_VISIBLE) PendingSlotRows(report.pending)
        Spacer(Modifier.height(24.dp))
        HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
        Spacer(Modifier.height(8.dp))
        Text(
            "A measure shows only when the session meets its minimum window and coverage; otherwise the reason. " +
                "Methods were checked on public data (MIT-BIH, BIDMC), not yet on this ring.",
            style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
        )
        Spacer(Modifier.height(4.dp))
        Text(report.versions, style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted)
        if (onHistory != null || onDelete != null) {
            Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                onHistory?.let { PlainButton("History", it, modifier = Modifier.weight(1f)) }
                onDelete?.let { PlainButton("Delete", it, modifier = Modifier.weight(1f)) }
            }
        }
        Spacer(Modifier.height(16.dp).testTag(REPORT_END))
    }
}

private fun summaryLine(r: SessionReport): String {
    val good = "Good signal ${(100 * r.goodShare).roundToInt()}% of the time"
    val total = r.durationS * EcgFilter.ECG_SAMPLE_RATE
    val lost = if (r.samplesLost == 0L) "no samples lost"
               else "${r.samplesLost} samples lost (${formatValue(100.0 * r.samplesLost / total, 1)}%)"
    return "$good · $lost · ${r.beats} beats"
}

@Composable
private fun ReportSection(title: String) {
    Spacer(Modifier.height(18.dp))
    Text(title.uppercase(Locale.UK), style = MaterialTheme.typography.labelMedium, color = MonitorColors.TextMuted)
    Spacer(Modifier.height(4.dp))
    HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
}

@Composable
private fun MeasureRow(spec: MeasureSpec, m: Measure?) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                spec.label, style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text,
                modifier = Modifier.weight(1f).alignByBaseline(),
            )
            val v = m?.value
            if (v != null) {
                Text(
                    formatValue(v, spec.decimals), style = MaterialTheme.typography.headlineSmall.copy(fontFamily = PlexSansCondensed),
                    color = MonitorColors.Text, modifier = Modifier.alignByBaseline(),
                )
                if (spec.unit.isNotEmpty()) Text(
                    " ${spec.unit}", style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted,
                    modifier = Modifier.alignByBaseline(),
                )
            } else {
                Text(
                    "—", style = MaterialTheme.typography.headlineSmall, color = MonitorColors.TextMuted,
                    modifier = Modifier.alignByBaseline(),
                )
            }
        }
        val detail = when {
            m == null -> "not computed"
            m.value == null -> m.withheld ?: "withheld"
            spec.key == "br" -> breathingDetail(m)
            spec.key == "hr" -> "median of ${m.nUsed} ${spec.noun}"
            else -> "${m.nUsed} ${spec.noun} · coverage ${(100 * m.coverage).roundToInt()}%"
        }
        Text(detail, style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted)
    }
}

private fun breathingDetail(m: Measure): String {
    val windows = if (m.coverage > 0) (m.nUsed / m.coverage).roundToInt() else 0
    val range = if (m.min != null && m.max != null) ", range ${formatValue(m.min, 1)}–${formatValue(m.max, 1)}" else ""
    return "median of ${m.nUsed} of $windows windows$range"
}

@Composable
private fun PendingSlotRows(p: PendingSlots) {
    ReportSection("Rhythm and context")
    Field("Rhythm check", p.rhythm ?: "—")
    Field("Ectopic beats", p.ectopicCount?.toString() ?: "—")
    Field("Motion", p.motionShare?.let { "${(100 * it).roundToInt()}% of the time" } ?: "—")
    Field("Arousal vs baseline", p.arousal?.let { formatValue(it, 1) } ?: "—")
}

// ----------------------------------------------------------------- history

/** The measures a trend can be drawn for, in chip order. */
internal val TREND_KEYS = listOf("hr", "rmssd", "br", "sdnn", "pnn50", "sd1", "sd2", "lf", "hf", "lf_hf", "dfa_alpha1")

@Composable
fun HistoryScreen(
    reports: List<SessionReport>, selected: String, onSelect: (String) -> Unit,
    onOpen: (SessionReport) -> Unit, onBack: () -> Unit, insets: PaddingValues,
) {
    Page("History", insets, "Back", onBack) {
        if (reports.isEmpty()) {
            Spacer(Modifier.height(16.dp))
            Text("No sessions yet", style = NoDataStyle, color = MonitorColors.Text)
            Spacer(Modifier.height(8.dp))
            Muted("A session takes ${SessionConfig.DURATION_S.toInt() / 60} minutes. Each one is kept here, on this phone only.")
            return@Page
        }
        val spec = ALL_SPECS.first { it.key == selected }
        Spacer(Modifier.height(8.dp))
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (k in TREND_KEYS) {
                val s = ALL_SPECS.first { it.key == k }
                FilterChip(
                    k == selected, { onSelect(k) }, label = { Text(s.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MonitorColors.GridMajor, selectedLabelColor = MonitorColors.Text,
                        labelColor = MonitorColors.TextMuted,
                    ),
                )
            }
        }
        // Oldest on the left.
        val chrono = reports.sortedBy { it.startedAtMs }
        val values = chrono.map { it.measures[selected]?.value }
        val shown = values.filterNotNull()
        Spacer(Modifier.height(12.dp))
        Text(
            if (spec.unit.isEmpty()) spec.label else "${spec.label}, ${spec.unit}",
            style = MaterialTheme.typography.labelMedium, color = MonitorColors.TextMuted,
        )
        Spacer(Modifier.height(4.dp))
        Trend(values, chrono.map { it.replayFile != null }, spec)
        Spacer(Modifier.height(6.dp))
        val med = if (shown.isEmpty()) null else com.dhruv.ecgmonitor.algorithms.median(shown.toDoubleArray())
        val unit = if (spec.unit.isEmpty()) "" else " " + spec.unit
        Muted(
            buildString {
                append("${shown.size} of ${chrono.size} sessions have a value.")
                if (med != null) append(" Dashed: their median, ${formatValue(med, spec.decimals)}$unit.")
                if (chrono.any { it.replayFile != null }) append(" Squares are replays.")
                if (shown.size < chrono.size) append(" A tick under the axis: withheld.")
            }
        )
        if (selected == "sdnn") Muted("SDNN grows with recording length: compare sessions of the same length only.")
        if (selected == "lf_hf") Muted(LF_HF_CAVEAT)
        Spacer(Modifier.height(16.dp))
        for (r in reports) HistoryRow(r, onOpen)
        Spacer(Modifier.height(16.dp))
    }
}

// One point per session, oldest on the left, no lines between them: sessions
// are separate recordings. The extreme values are labelled on their own
// gridlines; the dashed line is the median of the sessions shown.
@Composable
private fun Trend(values: List<Double?>, replay: List<Boolean>, spec: MeasureSpec) {
    val shown = values.filterNotNull()
    val lo = shown.minOrNull(); val hi = shown.maxOrNull()
    val pad = if (lo != null && hi != null) maxOf((hi - lo) * 0.15, 0.05 * maxOf(kotlin.math.abs(hi), 1.0)) else 1.0
    val yMin = (lo ?: 0.0) - pad; val yMax = (hi ?: 1.0) + pad
    val med = if (shown.isEmpty()) null else com.dhruv.ecgmonitor.algorithms.median(shown.toDoubleArray())
    val measurer = rememberTextMeasurer()
    val labelStyle = MaterialTheme.typography.labelSmall.copy(color = MonitorColors.TextMuted)
    Canvas(
        Modifier.fillMaxWidth().height(180.dp)
            .semantics { contentDescription = "${spec.label} over ${values.size} sessions, ${shown.size} with a value" }
    ) {
        val labelW = 44.dp.toPx()
        val left = labelW + 8.dp.toPx(); val right = size.width - 8.dp.toPx()
        val axisY = size.height - 12.dp.toPx()
        val n = values.size
        fun x(i: Int) = if (n == 1) (left + right) / 2 else left + i * (right - left) / (n - 1)
        fun y(v: Double) = (axisY - 6.dp.toPx() - (v - yMin) / (yMax - yMin) * (axisY - 12.dp.toPx())).toFloat()
        fun label(v: Double) {
            val t = measurer.measure(formatValue(v, spec.decimals), labelStyle)
            drawText(t, topLeft = Offset(labelW - t.size.width, y(v) - t.size.height / 2f))
        }
        drawLine(MonitorColors.GridMajor, Offset(labelW + 4.dp.toPx(), axisY), Offset(size.width, axisY), 1.dp.toPx())
        if (hi != null && lo != null) {
            for (v in if (hi > lo) listOf(hi, lo) else listOf(hi)) {
                drawLine(MonitorColors.GridMinor, Offset(labelW + 4.dp.toPx(), y(v)), Offset(size.width, y(v)), 1.dp.toPx())
                label(v)
            }
        }
        med?.let {
            drawLine(
                MonitorColors.TextMuted, Offset(labelW + 4.dp.toPx(), y(it)), Offset(size.width, y(it)), 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx())),
            )
        }
        val r = 4.dp.toPx()
        for (i in 0 until n) {
            val v = values[i]
            if (v == null) {
                // Withheld: a short tick below the axis, never a point at zero.
                drawLine(MonitorColors.TextMuted, Offset(x(i), axisY + 3.dp.toPx()), Offset(x(i), axisY + 9.dp.toPx()), 1.5.dp.toPx())
                continue
            }
            val c = Offset(x(i), y(v))
            // Filled black first, so the median line doesn't show through a square.
            if (replay[i]) {
                drawRect(MonitorColors.Black, c - Offset(r, r), Size(2 * r, 2 * r))
                drawRect(MonitorColors.Text, c - Offset(r, r), Size(2 * r, 2 * r), style = Stroke(1.5.dp.toPx()))
            } else drawCircle(MonitorColors.Text, r, c)
        }
    }
}

@Composable
private fun HistoryRow(r: SessionReport, onOpen: (SessionReport) -> Unit) {
    HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
    Column(Modifier.fillMaxWidth().clickable(role = Role.Button) { onOpen(r) }.padding(vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(reportDate(r.startedAtMs), style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text, modifier = Modifier.weight(1f))
            if (r.replayFile != null) Box { ReplayTag(r.replayFile) }
            Muted(" ›")
        }
        val parts = listOf("hr" to "HR", "rmssd" to "RMSSD", "br" to "Breathing").map { (k, short) ->
            val s = ALL_SPECS.first { it.key == k }
            val v = r.measures[k]?.value
            "$short ${v?.let { formatValue(it, s.decimals) + if (s.unit.isEmpty()) "" else " " + s.unit } ?: "—"}"
        }
        Muted(parts.joinToString(" · "))
    }
}
