package com.dhruv.ecgmonitor

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.dhruv.ecgmonitor.algorithms.Result
import kotlin.math.ceil
import kotlin.math.roundToInt

// Guided breathing: a pacer at 6 breaths a minute and, beside it, the live
// effect on the heart. Everything measured comes from the ported algorithms
// on sliding windows (LiveHrv.kt), with the same minimums as the report.

class BreathingUiState(
    val phase: BreathingPhase,
    /** Seconds since Start by the wall clock; drives the pacer. */
    val elapsedS: Double,
    val snapshot: LiveSnapshot?,
    val monitor: MonitorUiState,
)

class BreathingActions(val onStart: () -> Unit = {}, val onStop: () -> Unit = {}, val onBack: () -> Unit = {})

@Composable
fun GuidedBreathingScreen(state: BreathingUiState, actions: BreathingActions, geometry: ScreenGeometry) {
    val running = state.phase is BreathingPhase.Running
    val total = GuidedBreathingConfig.DURATION_S
    val p = pacer(if (running) state.elapsedS else 0.0)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val landscape = maxWidth > maxHeight
        Page(
            "Guided breathing", geometry.insets,
            if (running) "Stop" else "Back", if (running) actions.onStop else actions.onBack,
        ) {
            state.monitor.replayFile?.let { Spacer(Modifier.height(6.dp)); ReplayTag(it) }
            if (landscape) Row {
                Column(Modifier.weight(0.42f).padding(end = 20.dp)) { PacerBlock(state, p, total, actions, maxPacer = 120) }
                Column(Modifier.weight(0.58f)) { LiveBlock(state) }
            } else {
                PacerBlock(state, p, total, actions, maxPacer = 210)
                LiveBlock(state)
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun ColumnScope.PacerBlock(state: BreathingUiState, p: PacerPhase, total: Double, actions: BreathingActions, maxPacer: Int) {
    val running = state.phase is BreathingPhase.Running
    Spacer(Modifier.height(12.dp))
    Box(
        Modifier.align(Alignment.CenterHorizontally).widthIn(max = maxPacer.dp).fillMaxWidth().aspectRatio(1f),
        contentAlignment = Alignment.Center,
    ) {
        // At rest the circle sits half-way; it only moves while running.
        Pacer(if (running) p.size else 0.5)
    }
    // The instruction under the circle, never on it: at its smallest the
    // circle is too small to hold text.
    Spacer(Modifier.height(10.dp))
    Row(Modifier.align(Alignment.CenterHorizontally), verticalAlignment = Alignment.Bottom) {
        when (state.phase) {
            is BreathingPhase.Running -> {
                Text(if (p.inhale) "Breathe in" else "Breathe out", style = MaterialTheme.typography.headlineSmall,
                    color = MonitorColors.Text, modifier = Modifier.alignByBaseline())
                Text("  ${ceil(p.secondsLeftInPhase).toInt()}", style = MaterialTheme.typography.headlineSmall.copy(fontFamily = PlexSansCondensed),
                    color = MonitorColors.TextMuted, modifier = Modifier.alignByBaseline())
            }
            is BreathingPhase.Done -> Text("Done", style = MaterialTheme.typography.headlineSmall, color = MonitorColors.Text)
            else -> Text(
                "${GuidedBreathingConfig.PACE_PER_MIN.roundToInt()} breaths a minute", style = MaterialTheme.typography.headlineSmall,
                color = MonitorColors.Text,
            )
        }
    }
    Spacer(Modifier.height(6.dp))
    when (state.phase) {
        is BreathingPhase.Running -> {
            val left = (total - state.elapsedS).coerceAtLeast(0.0)
            val breaths = (total / (GuidedBreathingConfig.INHALE_S + GuidedBreathingConfig.EXHALE_S)).toInt()
            Text(
                "${clock(ceil(left).toInt())} left · breath ${minOf(p.breath + 1, breaths)} of $breaths",
                style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(),
            )
        }
        is BreathingPhase.Done -> {
            Muted("Done. Breathe normally. The numbers below are the last windows of the exercise.")
            Spacer(Modifier.height(12.dp))
            PlainButton("Again", actions.onStart, modifier = Modifier.fillMaxWidth())
        }
        else -> {
            // The button before the explanation, so it is on screen in landscape too.
            Spacer(Modifier.height(6.dp))
            PlainButton("Start", actions.onStart, enabled = state.monitor.link == Link.RECEIVING, modifier = Modifier.fillMaxWidth())
            if (state.monitor.link != Link.RECEIVING) { Spacer(Modifier.height(6.dp)); Muted("Connect the ring first.") }
            Spacer(Modifier.height(12.dp))
            Muted(
                "Breathe in while the circle grows (${GuidedBreathingConfig.INHALE_S.roundToInt()} s), out while it shrinks " +
                    "(${GuidedBreathingConfig.EXHALE_S.roundToInt()} s), for ${clock(total.toInt())}. Slow breathing makes the " +
                    "heart rate rise and fall with each breath; the curve shows it."
            )
        }
    }
}

// A filled circle between a quarter and the full size of its outline.
@Composable
private fun Pacer(size: Double) {
    Canvas(Modifier.fillMaxSize().semantics { contentDescription = "breathing pacer" }) {
        val rMax = this.size.minDimension / 2 - 2.dp.toPx()
        val rMin = rMax * 0.25f
        val r = rMin + (rMax - rMin) * size.toFloat()
        drawCircle(MonitorColors.GridMajor, rMax, style = Stroke(1.5.dp.toPx()))
        drawCircle(MonitorColors.GridMinor, r)
        drawCircle(MonitorColors.Text, r, style = Stroke(2.dp.toPx()))
    }
}

@Composable
private fun LiveBlock(state: BreathingUiState) {
    val s = state.snapshot
    Spacer(Modifier.height(16.dp))
    HorizontalDivider(color = MonitorColors.GridMajor, thickness = 1.dp)
    val hr = when (val h = state.monitor.headline) {
        is Headline.Rate -> "${h.bpm}" to null
        is Headline.Hidden -> null to h.cause
        is Headline.NoData -> null to h.message
    }
    LiveRow("Heart rate", hr.first, "bpm", hr.second ?: "live, shown on a good signal only")
    LiveRow(
        "RMSSD, last ${GuidedBreathingConfig.RMSSD_WINDOW_S.toInt()} s", s?.rmssd?.value?.let { formatValue(it, 0) }, "ms",
        s?.rmssd?.let { detail(it, "successive differences") } ?: "waiting for data",
    )
    LiveRow(
        "Your breathing, last ${AlgConfig.BR_WINDOW_S.toInt()} s", s?.breathing?.value?.let { formatValue(it, 1) }, "/min",
        s?.breathing?.withheld ?: if (s == null) "waiting for data" else "pacer: ${formatValue(GuidedBreathingConfig.PACE_PER_MIN, 1)} /min",
    )
    Spacer(Modifier.height(12.dp))
    Text(
        "Heart rate, beat by beat, last ${GuidedBreathingConfig.CURVE_S.toInt()} s",
        style = MaterialTheme.typography.labelMedium, color = MonitorColors.TextMuted,
    )
    Spacer(Modifier.height(4.dp))
    val startIndex = when (val ph = state.phase) {
        is BreathingPhase.Running -> ph.startIndex
        is BreathingPhase.Done -> ph.startIndex
        else -> null
    }
    HrCurve(s, startIndex?.let { it / EcgFilter.ECG_SAMPLE_RATE })
    Spacer(Modifier.height(4.dp))
    Muted(
        if (startIndex != null) "Shaded: breathe in. On slow breathing the curve should rise on each in-breath and fall on each out-breath."
        else "Gaps are beats the detector could not time; they are never joined."
    )
}

private typealias AlgConfig = com.dhruv.ecgmonitor.algorithms.AlgConfig

private fun detail(r: Result, noun: String) =
    r.withheld ?: "${r.nUsed} $noun · coverage ${(100 * r.coverage).roundToInt()}%"

@Composable
private fun LiveRow(label: String, value: String?, unit: String, detail: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(label, style = MaterialTheme.typography.bodyLarge, color = MonitorColors.Text, modifier = Modifier.weight(1f).alignByBaseline())
            if (value != null) {
                Text(
                    value, style = MaterialTheme.typography.headlineSmall.copy(fontFamily = PlexSansCondensed),
                    color = MonitorColors.Text, modifier = Modifier.alignByBaseline(),
                )
                Text(" $unit", style = MaterialTheme.typography.bodyMedium, color = MonitorColors.TextMuted, modifier = Modifier.alignByBaseline())
            } else Text("—", style = MaterialTheme.typography.headlineSmall, color = MonitorColors.TextMuted, modifier = Modifier.alignByBaseline())
        }
        Text(detail, style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted)
    }
}

// Instantaneous heart rate (60 / NN interval) at each accepted beat over the
// last CURVE_S, joined only between successive accepted intervals; the inhale
// phases of the pacer shaded behind it, on the sample clock.
@Composable
private fun HrCurve(s: LiveSnapshot?, startS: Double?) {
    val measurer = rememberTextMeasurer()
    val labelStyle = MaterialTheme.typography.labelSmall.copy(color = MonitorColors.TextMuted)
    val pts = s?.curve.orEmpty()
    val vals = pts.map { it.second }.filter { it.isFinite() }
    Canvas(
        Modifier.fillMaxWidth().height(130.dp)
            .semantics { contentDescription = "beat-to-beat heart rate, ${vals.size} beats" }
    ) {
        val labelW = 36.dp.toPx()
        val left = labelW + 6.dp.toPx(); val right = size.width
        val top = 6.dp.toPx(); val bottom = size.height - 6.dp.toPx()
        drawRect(MonitorColors.GridMajor, Offset(left, top), Size(right - left, bottom - top), style = Stroke(1.dp.toPx()))
        if (s == null) return@Canvas
        val t1 = s.t1; val t0 = t1 - GuidedBreathingConfig.CURVE_S
        fun x(t: Double) = (left + (t - t0) / (t1 - t0) * (right - left)).toFloat()
        // Inhale bands.
        if (startS != null) {
            val cycle = GuidedBreathingConfig.INHALE_S + GuidedBreathingConfig.EXHALE_S
            var k = maxOf(0, kotlin.math.floor((t0 - startS) / cycle).toInt())
            while (startS + k * cycle < t1 && k * cycle < GuidedBreathingConfig.DURATION_S) {
                val a = maxOf(startS + k * cycle, t0); val b = minOf(startS + k * cycle + GuidedBreathingConfig.INHALE_S, t1)
                if (b > a) drawRect(MonitorColors.GridMinor, Offset(x(a), top), Size(x(b) - x(a), bottom - top))
                k++
            }
        }
        if (vals.isEmpty()) return@Canvas
        val lo = vals.min(); val hi = vals.max()
        val pad = maxOf((hi - lo) * 0.15, 2.0)
        val yMin = lo - pad; val yMax = hi + pad
        fun y(v: Double) = (bottom - (v - yMin) / (yMax - yMin) * (bottom - top)).toFloat()
        for (v in listOf(hi, lo)) {
            val t = measurer.measure(formatValue(v, 0), labelStyle)
            drawText(t, topLeft = Offset(labelW - t.size.width, y(v) - t.size.height / 2f))
        }
        val path = Path()
        var open = false
        for ((t, bpm) in pts) {
            if (!bpm.isFinite() || t < t0) { open = false; continue }
            if (open) path.lineTo(x(t), y(bpm)) else path.moveTo(x(t), y(bpm))
            open = true
        }
        drawPath(path, MonitorColors.Text, style = Stroke(1.5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        for ((t, bpm) in pts) if (bpm.isFinite() && t >= t0) drawCircle(MonitorColors.Text, 2.dp.toPx(), Offset(x(t), y(bpm)))
    }
}
