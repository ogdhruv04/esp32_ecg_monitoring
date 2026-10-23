package com.dhruv.ecgmonitor

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt

// Nominal ADC codes per millivolt: 2^17 * gain 20 / VREF 1000 mV
// (docs/MAX30003_datasheet_check.md #23; nominal, not verified on our boards).
const val NOMINAL_CODES_PER_MV = (1 shl 17) * 20 / 1000f

const val PAPER_SPEED_MM_PER_S = 25f
val GAINS_MM_PER_MV = listOf(10, 20, 40)
// 40, not the standard 10, while our signal is tiny at the nominal scale
// (root CLAUDE.md status). Back to 10 once that amplitude issue is resolved.
const val DEFAULT_GAIN_MM_PER_MV = 40

/**
 * ECG paper and sweep trace. The grid is 1 mm / 5 mm in real millimetres,
 * from the screen's physical DPI (xdpi/ydpi), not from dp. The trace is
 * written left to right at a fixed place per sample and wraps, leaving an
 * erase gap ahead of the write head; it never scrolls or autoscales. A 1 mV
 * calibration pulse at the left edge shows the current gain.
 *
 * `tick` is read only so the trace redraws when new samples arrive.
 */
@Composable
fun EcgTrace(
    buffer: SweepBuffer,
    tick: Int,
    showTrace: Boolean,
    mmPerMv: Int,
    xdpi: Float,
    ydpi: Float,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier) {
        @Suppress("UNUSED_EXPRESSION") tick
        val pxPerMmX = xdpi / 25.4f
        val pxPerMmY = ydpi / 25.4f
        // 0 mV sits on a major line: the one nearest the middle, or lower if
        // the 1 mV calibration pulse would otherwise run off the top (at
        // 40 mm/mV the pulse is 40 mm tall). The pulse is the scale
        // reference, so it must always be seen whole.
        val major = 5 * pxPerMmY
        val middle = (size.height / 2 / major).roundToInt() * major
        val pulseRoom = ceil((mmPerMv + PULSE_HEADROOM_MM) * pxPerMmY / major) * major
        // If even that won't fit (a very short strip), keep 0 mV on screen.
        val lowest = floor((size.height - major) / major) * major
        val baseline = maxOf(middle, pulseRoom).coerceAtMost(maxOf(lowest, major))

        drawPaper(pxPerMmX, pxPerMmY, baseline)
        if (!showTrace) return@Canvas

        val pxPerMv = mmPerMv * pxPerMmY
        val stroke = Stroke(
            width = TRACE_STROKE.toPx(), join = StrokeJoin.Round, cap = StrokeCap.Round,
        )
        clipRect {
            // Muted: it is a scale reference, not signal.
            drawPath(calibrationPulse(pxPerMmX, baseline, pxPerMv), MonitorColors.TextMuted, style = stroke)

            val x0 = snap(CAL_GUTTER_MM * pxPerMmX)
            val pxPerSample = PAPER_SPEED_MM_PER_S * pxPerMmX / EcgFilter.ECG_SAMPLE_RATE.toFloat()
            val columns = floor((size.width - x0) / pxPerSample).toInt()
            val erase = (ERASE_SECONDS * EcgFilter.ECG_SAMPLE_RATE).roundToInt()
            val path = Path()
            for (run in sweepRuns(buffer, columns, erase)) {
                for (n in run.first..run.last) {
                    val x = x0 + (n % columns) * pxPerSample
                    val y = baseline - buffer[n] / NOMINAL_CODES_PER_MV * pxPerMv
                    if (n == run.first) path.moveTo(x, y) else path.lineTo(x, y)
                }
            }
            drawPath(path, MonitorColors.Trace, style = stroke)
        }
    }
}

// Paper speed and gain, with the gain tappable to cycle 10 / 20 / 40 mm/mV.
// "· raw" when the trace is the unfiltered signal, so the view is never ambiguous.
@Composable
fun TraceCaption(mmPerMv: Int, raw: Boolean, onCycleGain: () -> Unit, modifier: Modifier = Modifier) {
    val style = TextStyle(
        fontFamily = PlexSans, fontSize = 12.sp, fontFeatureSettings = TABULAR,
        color = MonitorColors.TextMuted,
    )
    // Phrases wrap as units at a large system font instead of being squeezed.
    @OptIn(ExperimentalLayoutApi::class)
    FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        val center = Modifier.align(Alignment.CenterVertically)
        Text("${PAPER_SPEED_MM_PER_S.roundToInt()} mm/s ·", style = style, modifier = center)
        Text(
            "$mmPerMv mm/mV",
            // Underlined so it reads as tappable without relying on colour.
            style = style.copy(textDecoration = TextDecoration.Underline),
            modifier = center
                .minimumInteractiveComponentSize()
                .clickable(onClickLabel = "change gain", role = Role.Button, onClick = onCycleGain),
        )
        Text(if (raw) "(nominal) · raw" else "(nominal)", style = style, modifier = center)
    }
}

fun nextGain(current: Int): Int =
    GAINS_MM_PER_MV[(GAINS_MM_PER_MV.indexOf(current) + 1) % GAINS_MM_PER_MV.size]

private val TRACE_STROKE = 1.5.dp
private const val ERASE_SECONDS = 0.2
// Room at the left edge for the calibration pulse: 2 mm lead-in, 5 mm pulse
// (0.2 s at 25 mm/s), 2 mm lead-out, 1 mm clear. Two major squares, so the
// sweep starts on a major line.
private const val CAL_GUTTER_MM = 10f
// Clear space kept above the top of the calibration pulse.
private const val PULSE_HEADROOM_MM = 2f

private fun snap(x: Float) = x.roundToInt().toFloat()

private fun DrawScope.drawPaper(pxPerMmX: Float, pxPerMmY: Float, baseline: Float) {
    val thin = 1f
    val thick = 2f
    var k = 0
    while (k * pxPerMmX <= size.width) {
        val x = snap(k * pxPerMmX)
        val major = k % 5 == 0
        drawLine(
            if (major) MonitorColors.GridMajor else MonitorColors.GridMinor,
            Offset(x, 0f), Offset(x, size.height), if (major) thick else thin,
        )
        k++
    }
    // Rows counted from the baseline, so 0 mV is always a major line.
    val first = -floor(baseline / pxPerMmY).toInt()
    var j = first
    while (baseline + j * pxPerMmY <= size.height) {
        val y = snap(baseline + j * pxPerMmY)
        val major = Math.floorMod(j, 5) == 0
        drawLine(
            if (major) MonitorColors.GridMajor else MonitorColors.GridMinor,
            Offset(0f, y), Offset(size.width, y), if (major) thick else thin,
        )
        j++
    }
}

private fun calibrationPulse(pxPerMmX: Float, baseline: Float, pxPerMv: Float) = Path().apply {
    val top = baseline - pxPerMv
    moveTo(0f, baseline)
    lineTo(snap(2 * pxPerMmX), baseline)
    lineTo(snap(2 * pxPerMmX), top)
    lineTo(snap(7 * pxPerMmX), top)
    lineTo(snap(7 * pxPerMmX), baseline)
    lineTo(snap(9 * pxPerMmX), baseline)
}
