package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/**
 * BeatDetector.kt must stay algorithmically identical to pan_tompkins.py, which
 * is the version benchmarked against MIT-BIH. These tests feed both the same
 * real recording and require the same beats at the same tp2 positions, with the
 * same flags, and the same HRV.
 *
 * Fixtures come from make_parity_fixtures.py at the repository root. If
 * pan_tompkins.py changes, regenerate them, and expect this test to fail until
 * the Kotlin port matches.
 */
class BeatDetectorParityTest {

    private data class Beat(val pos: Double, val flagged: Boolean)
    private data class Fixture(val values: FloatArray, val skips: IntArray, val expected: List<Beat>)

    private fun load(name: String): Fixture {
        val input = resource("parity/${name}_input.csv").lineSequence().drop(1)
            .filter { it.isNotBlank() }.map { it.split(',') }.toList()
        val expected = resource("parity/${name}_expected.txt").lineSequence()
            .filter { it.isNotBlank() }.map { it.split(',') }
            .map { Beat(it[0].toDouble(), it[1].trim() == "1") }.toList()
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

    private fun detect(f: Fixture, detector: BeatDetector = BeatDetector()): List<Beat> {
        val beats = ArrayList<Beat>()
        for (i in f.values.indices) {
            if (f.skips[i] > 0) detector.skip(f.skips[i])
            if (detector.process(f.values[i]) != null)
                beats.add(Beat(detector.lastBeatPosition, detector.lastBeatFlagged))
        }
        return beats
    }

    private fun assertParity(name: String) {
        val f = load(name)
        val d = BeatDetector()
        val kotlin = detect(f, d)
        // Report the first disagreement, not just the counts: a sub-sample shift
        // and a missed beat look identical in a count.
        val firstDiff = (0 until maxOf(kotlin.size, f.expected.size)).firstOrNull { k ->
            val a = kotlin.getOrNull(k); val b = f.expected.getOrNull(k)
            a == null || b == null || abs(a.pos - b.pos) > 1e-9 || a.flagged != b.flagged
        }
        assertEquals(
            "$name: Kotlin ${kotlin.size} beats, Python ${f.expected.size}; first difference at beat " +
                "$firstDiff (kotlin ${firstDiff?.let { kotlin.getOrNull(it) }}, python " +
                "${firstDiff?.let { f.expected.getOrNull(it) }})",
            null, firstDiff
        )
    }

    @Test fun chestRecordingMatchesPython() = assertParity("chest")

    @Test fun fingerRecordingMatchesPython() = assertParity("finger")

    /** A 40x artifact followed by lost packets: exercises stall decay and skip(). */
    @Test fun artifactAndGapsMatchPython() = assertParity("artifact_gaps")

    /** Sign inverted at 30 s: the per-beat correlation check flags the beats the
     *  old-sign median beat would time on the wrong lobe, the rolling polarity
     *  goes undecided, then settles on the other sign. */
    @Test fun polarityFlipMatchesPython() = assertParity("polarity_flip")

    @Test fun detectorRecoversAfterArtifact() {
        // The bug this guards against: before stall decay, one large transient
        // left the detector silent for the rest of the session (0 beats in the
        // 48 s after this artifact, against 79 with the fix).
        val beats = detect(load("artifact_gaps"))
        val after = beats.count { it.pos > 11.5 * 256 }
        assertTrue("only $after beats after the artifact", after >= 70)
    }

    /**
     * The phone's HRV path against pan_tompkins.rr_history + rmssd_nn on the same
     * input: RMSSD, accepted and dropped NN counts. Exact agreement, not closeness
     * to an offline figure - this pins the computation, not the physiology.
     */
    private fun assertRmssdParity(name: String) {
        val f = load(name)
        val d = BeatDetector()
        for (i in f.values.indices) {
            if (f.skips[i] > 0) d.skip(f.skips[i])
            d.process(f.values[i])
        }
        val e = resource("parity/${name}_rmssd.txt").trim().split(',')
        val expected = e[0].toDouble(); val dropped = e[2].trim().toInt(); val coverage = e[3].trim().toDouble()
        val got = d.rmssdMs
        println("$name RMSSD phone $got ms, python $expected ms; dropped ${d.nnDropped} vs $dropped; " +
                "coverage ${d.hrvCoverage} vs $coverage; followed peak picked again ${d.repicked}x")
        if (expected.isNaN()) assertNull("$name: phone shows an RMSSD Python withholds", got)
        else {
            assertNotNull("$name: no RMSSD from ${d.beatCount} intervals", got)
            assertEquals("$name RMSSD", expected, got!!, 1e-9)
        }
        assertEquals("$name NN intervals dropped", dropped, d.nnDropped)
        assertEquals("$name HRV coverage", coverage, d.hrvCoverage, 1e-12)
    }

    @Test fun chestRmssdMatchesPython() = assertRmssdParity("chest")

    @Test fun fingerRmssdMatchesPython() = assertRmssdParity("finger")

    @Test fun artifactRmssdMatchesPython() = assertRmssdParity("artifact_gaps")

    @Test fun polarityFlipRmssdMatchesPython() = assertRmssdParity("polarity_flip")

    @Test fun skipKeepsTimeAcrossTheGap() {
        // Dropping 30 samples and telling the detector must land every later
        // beat on the original timeline, not 30 samples early.
        val f = load("chest")
        val cut = 30 * 256; val lost = 30
        val values = f.values.filterIndexed { i, _ -> i !in cut until cut + lost }.toFloatArray()
        val skips = IntArray(values.size).also { it[cut] = lost }
        val withGap = detect(Fixture(values, skips, emptyList()))
        val late = { p: List<Beat> -> p.filter { it.pos > cut + 5 * 256 }.map { it.pos } }
        val reference = late(detect(f))
        val shifted = late(withGap)
        val common = minOf(reference.size, shifted.size)
        assertTrue("too few beats to compare", common > 20)
        // The filters see a 117 ms splice, so allow one sample of disagreement.
        for (k in 0 until common) {
            assertTrue("beat $k: ${shifted[k]} vs ${reference[k]}", abs(shifted[k] - reference[k]) <= 1.0)
        }
    }
}
