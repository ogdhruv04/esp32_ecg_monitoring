package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * BeatDetector.kt must stay algorithmically identical to pan_tompkins.py, which
 * is the version benchmarked against MIT-BIH. These tests feed both the same
 * real recording and require the same beats, sample for sample.
 *
 * Fixtures come from make_parity_fixtures.py at the repository root. If
 * pan_tompkins.py changes, regenerate them, and expect this test to fail until
 * the Kotlin port matches.
 */
class BeatDetectorParityTest {

    private data class Fixture(val values: FloatArray, val skips: IntArray, val expected: List<Long>)

    private fun load(name: String): Fixture {
        val input = resource("parity/${name}_input.csv").lineSequence().drop(1)
            .filter { it.isNotBlank() }.map { it.split(',') }.toList()
        val expected = resource("parity/${name}_expected.txt").lineSequence()
            .filter { it.isNotBlank() }.map { it.trim().toLong() }.toList()
        return Fixture(
            FloatArray(input.size) { input[it][0].toFloat() },
            IntArray(input.size) { input[it][1].toInt() },
            expected
        )
    }

    private fun resource(path: String): String {
        val url = javaClass.classLoader!!.getResource(path)
        assertNotNull("missing fixture $path - run make_parity_fixtures.py", url)
        return url!!.readText()
    }

    private fun detect(f: Fixture, detector: BeatDetector = BeatDetector()): List<Long> {
        val peaks = ArrayList<Long>()
        for (i in f.values.indices) {
            if (f.skips[i] > 0) detector.skip(f.skips[i])
            detector.process(f.values[i])?.let { peaks.add(it) }
        }
        return peaks
    }

    private fun assertParity(name: String) {
        val f = load(name)
        val kotlin = detect(f)
        // Report the first disagreement, not just the counts: a one-sample
        // shift and a missed beat look identical in a count.
        val firstDiff = kotlin.indices.firstOrNull { it >= f.expected.size || kotlin[it] != f.expected[it] }
            ?: if (kotlin.size < f.expected.size) kotlin.size else null
        assertEquals(
            "$name: Kotlin found ${kotlin.size} beats, Python ${f.expected.size}; first difference at beat " +
                "$firstDiff (kotlin ${firstDiff?.let { kotlin.getOrNull(it) }}, python " +
                "${firstDiff?.let { f.expected.getOrNull(it) }})",
            f.expected, kotlin
        )
    }

    @Test fun chestRecordingMatchesPython() = assertParity("chest")

    @Test fun fingerRecordingMatchesPython() = assertParity("finger")

    /** A 40x artifact followed by lost packets: exercises stall decay and skip(). */
    @Test fun artifactAndGapsMatchPython() = assertParity("artifact_gaps")

    @Test fun detectorRecoversAfterArtifact() {
        // The bug this guards against: before stall decay, one large transient
        // left the detector silent for the rest of the session (1 beat in the
        // 48 s after this artifact, against 80 with the fix).
        val peaks = detect(load("artifact_gaps"))
        val after = peaks.count { it > (11.5 * 256).toLong() }
        assertTrue("only $after beats after the artifact", after >= 70)
    }

    /**
     * The phone's HRV path, held to the same rules computed in Python by
     * make_parity_fixtures.py. Exact agreement, not closeness to an offline
     * figure: no RMSSD from our hardware is validated yet (see CLAUDE.md), so
     * this pins the computation, not the physiology.
     */
    private fun assertRmssdParity(name: String) {
        val f = load(name)
        val d = BeatDetector()
        for (i in f.values.indices) {
            if (f.skips[i] > 0) d.skip(f.skips[i])
            d.process(f.values[i])
        }
        val expected = resource("parity/${name}_rmssd.txt").trim().toDouble()
        val got = d.rmssdMs
        println("$name RMSSD phone $got ms, python $expected ms, ${d.beatCount} intervals")
        assertNotNull("$name: no RMSSD from ${d.beatCount} intervals", got)
        assertEquals("$name RMSSD", expected, got!!, 1e-9)
    }

    @Test fun chestRmssdMatchesPython() = assertRmssdParity("chest")

    @Test fun fingerRmssdMatchesPython() = assertRmssdParity("finger")

    @Test fun artifactRmssdMatchesPython() = assertRmssdParity("artifact_gaps")

    @Test fun skipKeepsTimeAcrossTheGap() {
        // Dropping 30 samples and telling the detector must land every later
        // beat on the original timeline, not 30 samples early.
        val f = load("chest")
        val cut = 30 * 256; val lost = 30
        val values = f.values.filterIndexed { i, _ -> i !in cut until cut + lost }.toFloatArray()
        val skips = IntArray(values.size).also { it[cut] = lost }
        val withGap = detect(Fixture(values, skips, emptyList()))
        val late = { p: List<Long> -> p.filter { it > cut + 5 * 256 } }
        val reference = late(detect(f))
        val shifted = late(withGap)
        val common = minOf(reference.size, shifted.size)
        assertTrue("too few beats to compare", common > 20)
        // The filters see a 117 ms splice, so allow one sample of disagreement.
        for (k in 0 until common) {
            assertTrue("beat $k: ${shifted[k]} vs ${reference[k]}",
                kotlin.math.abs(shifted[k] - reference[k]) <= 1)
        }
    }
}
