package com.dhruv.ecgmonitor

// Display history for the sweep trace, addressed by absolute sample number
// (lost samples included), so a sample's place on screen never changes once
// it is written. Lost samples are stored as NaN: the trace leaves a hole
// there instead of drawing a line across it.
class SweepBuffer(val capacity: Int = (EcgFilter.ECG_SAMPLE_RATE * SECONDS).toInt()) {
    private val data = FloatArray(capacity) { Float.NaN }

    // Samples written so far, lost ones included. The newest is total - 1.
    var total = 0L
        private set

    fun push(value: Float) {
        data[(total % capacity).toInt()] = value
        total++
    }

    fun skip(samples: Int) {
        val marked = minOf(samples, capacity)
        repeat(marked) { push(Float.NaN) }
        // Beyond one buffer's worth every slot is already NaN; just keep time.
        total += samples - marked
    }

    // NaN for a sample that was lost, not yet written, or already overwritten.
    operator fun get(n: Long): Float =
        if (n < 0 || n >= total || n < total - capacity) Float.NaN
        else data[(n % capacity).toInt()]

    companion object {
        // Longer than the widest sweep (a landscape phone is about 6 s at 25 mm/s).
        const val SECONDS = 10.0
    }
}

// An unbroken stretch of samples first..last to draw as one polyline.
data class SweepRun(val first: Long, val last: Long)

// Splits the visible part of a sweep into polylines. Sample n sits in column
// n % columns. The newest columns - eraseColumns samples are shown, so the
// eraseColumns ahead of the write head stay empty. A run never contains a lost
// sample and never crosses the wrap from the right edge back to the left, so
// nothing is ever drawn joining across a gap. Single samples are dropped:
// there is no line to draw.
fun sweepRuns(buffer: SweepBuffer, columns: Int, eraseColumns: Int): List<SweepRun> {
    val runs = ArrayList<SweepRun>()
    val head = buffer.total - 1
    if (head < 0 || columns <= eraseColumns) return runs
    val from = maxOf(0L, head - (columns - eraseColumns) + 1)
    var start = -1L
    for (n in from..head) {
        val present = !buffer[n].isNaN()
        val wraps = n % columns == 0L
        if (start >= 0 && (!present || wraps)) {
            if (n - 1 > start) runs += SweepRun(start, n - 1)
            start = -1
        }
        if (present && start < 0) start = n
    }
    if (start >= 0 && head > start) runs += SweepRun(start, head)
    return runs
}
