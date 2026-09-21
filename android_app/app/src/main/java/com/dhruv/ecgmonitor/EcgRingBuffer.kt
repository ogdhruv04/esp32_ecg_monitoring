package com.dhruv.ecgmonitor

// Fixed-capacity circular buffer of recent ECG samples. Default holds 5s at the
// firmware's 256 SPS rate - the previous default of 625 was sized for the old
// 128 SPS build and silently became 2.4s when the sample rate was doubled.
// Not thread-safe on its own: callers must only write from one thread (the BLE
// callback's posted main-thread handler here).
class EcgRingBuffer(
    private val capacity: Int = (EcgFilter.ECG_SAMPLE_RATE * SECONDS_SHOWN).toInt()
) {
    private val data = FloatArray(capacity)
    private var writeIndex = 0
    private var filled = 0

    fun push(value: Float) {
        data[writeIndex] = value
        writeIndex = (writeIndex + 1) % capacity
        if (filled < capacity) filled++
    }

    fun clear() { writeIndex = 0; filled = 0 }

    // Returns samples oldest-to-newest as a plain array, safe to read from Compose.
    fun snapshot(): FloatArray {
        if (filled < capacity) {
            return data.copyOfRange(0, filled)
        }
        val out = FloatArray(capacity)
        val tail = capacity - writeIndex
        System.arraycopy(data, writeIndex, out, 0, tail)
        System.arraycopy(data, 0, out, tail, writeIndex)
        return out
    }

    companion object { const val SECONDS_SHOWN = 5.0 }
}
