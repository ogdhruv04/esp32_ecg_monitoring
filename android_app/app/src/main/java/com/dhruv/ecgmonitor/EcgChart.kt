package com.dhruv.ecgmonitor

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke

// Full-redraw line chart of the ring buffer's current contents. No calibration
// or units attempted - these are ADC codes, not millivolts.
//
// Scaling is percentile-based rather than min/max. A single motion spike or a
// filter transient sets a min/max range far wider than the ECG itself, which
// squashes the whole trace flat against the middle of the chart and reads as
// "the signal died" when nothing is actually wrong with it.
@Composable
fun EcgChart(
    samples: FloatArray,
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF2A78D6)
) {
    Canvas(modifier = modifier) {
        if (samples.size < 2) return@Canvas

        val sorted = samples.copyOf().also { it.sort() }
        val lo = sorted[(sorted.size * 0.01f).toInt().coerceIn(0, sorted.size - 1)]
        val hi = sorted[(sorted.size * 0.99f).toInt().coerceIn(0, sorted.size - 1)]
        // Headroom so R-peaks clipped by the 99th percentile still stay visible.
        val mid = (hi + lo) / 2f
        val half = ((hi - lo) / 2f * 1.4f).coerceAtLeast(1f)
        val minV = mid - half
        val range = half * 2f

        val stepX = size.width / (samples.size - 1)
        val path = Path()
        for (i in samples.indices) {
            val x = i * stepX
            val norm = ((samples[i] - minV) / range).coerceIn(0f, 1f)
            val y = size.height - (norm * size.height)
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }

        drawPath(path = path, color = color, style = Stroke(width = 3f))

        // Mid-line for orientation, since there are no axis labels in this POC.
        drawLine(
            color = Color(0x22000000),
            start = Offset(0f, size.height / 2),
            end = Offset(size.width, size.height / 2),
            strokeWidth = 1f
        )
    }
}
