package com.dhruv.ecgmonitor

/**
 * Streaming running-median baseline removal, for DISPLAY ONLY.
 *
 * After the biquad chain the trace still wanders by ~0.47x the R-peak amplitude
 * on our bench recordings. That residual is respiration and electrode motion
 * sitting *inside* the passband, at and above the 0.5 Hz corner - raising the
 * high-pass order barely touches it (0.47 -> 0.47 at 2nd order, 0.47 at 6th),
 * because there is no stopband to push it into. Subtracting a running median
 * takes it to 0.09.
 *
 * A median is used rather than a mean because the QRS complex is a large, brief
 * excursion: it would drag a moving average upward, but it occupies only ~17% of
 * a 0.6 s window, so it barely moves the median.
 *
 * NOT applied in analyze.py's research chain. Median detrending alters the ST
 * segment, and anything making morphology claims has to run on the documented
 * filter chain alone. Verified display-safe for rate work: on a 5-minute resting
 * capture, beat count, HR and RMSSD were identical with and without it.
 */
class BaselineRemover(
    sampleRate: Double = EcgFilter.ECG_SAMPLE_RATE,
    windowSeconds: Double = 0.6
) {
    // Odd length so the median is a single element, not a two-element average.
    private val window: Int = ((sampleRate * windowSeconds).toInt()).let { if (it % 2 == 0) it + 1 else it }

    private val ring = FloatArray(window)          // insertion order, for eviction
    private val sorted = FloatArray(window)        // same values, kept ordered
    private var writeIndex = 0
    private var filled = 0

    fun process(x: Float): Float {
        if (filled < window) {
            // Warm-up: grow the window until it is full. Median of what we have.
            insertSorted(x, filled)
            ring[writeIndex] = x
            writeIndex = (writeIndex + 1) % window
            filled++
            return x - sorted[filled / 2]
        }

        val evicted = ring[writeIndex]
        removeSorted(evicted)
        insertSorted(x, window - 1)
        ring[writeIndex] = x
        writeIndex = (writeIndex + 1) % window
        return x - sorted[window / 2]
    }

    fun reset() { writeIndex = 0; filled = 0 }

    /** Binary-search for the insertion point, then shift. O(window) per sample. */
    private fun insertSorted(v: Float, currentSize: Int) {
        var lo = 0
        var hi = currentSize
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (sorted[mid] < v) lo = mid + 1 else hi = mid
        }
        System.arraycopy(sorted, lo, sorted, lo + 1, currentSize - lo)
        sorted[lo] = v
    }

    private fun removeSorted(v: Float) {
        var lo = 0
        var hi = window - 1
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (sorted[mid] < v) lo = mid + 1 else hi = mid
        }
        System.arraycopy(sorted, lo + 1, sorted, lo, window - 1 - lo)
    }
}
