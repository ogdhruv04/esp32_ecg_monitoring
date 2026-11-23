package com.dhruv.ecgmonitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.max

/**
 * SignalQuality.kt against its reference, signal_quality.py, on the fixtures
 * make_sqi_fixtures.py writes from real recordings (electrode-settling
 * transients, a burst of large swings, a clean recording, added noise). Each
 * fixture is the display and 5-15 Hz samples the gate is handed; the phone
 * must give the same kurtosis, band share and swing ratio (to 1e-9, relative)
 * and the same verdict at every assessment. The constants are checked
 * against sqi_config.json.
 */
class SignalQualityParityTest {

    private fun lines(path: String): List<String> =
        (javaClass.classLoader!!.getResource(path) ?: error("$path missing: run ./make_sqi_fixtures.py"))
            .readText().lineSequence().filter { it.isNotBlank() }.toList()

    private fun close(want: Double, got: Double) = abs(want - got) <= 1e-9 * max(1.0, abs(want))

    private fun case(name: String): Pair<Int, Int> {
        val input = lines("sqi/${name}_input.csv").drop(1).map { l -> l.split(',').let { it[0].toFloat() to it[1].toFloat() } }
        val expected = lines("sqi/${name}_expected.tsv").drop(1).map { it.split('\t') }.associateBy { it[0].toInt() }
        val gate = SignalQuality()
        val display = EcgRingBuffer(); val qrs = EcgRingBuffer()
        var checked = 0; var artifacts = 0
        for ((i, s) in input.withIndex()) {
            display.push(s.first); qrs.push(s.second); gate.track(s.first)
            val e = expected[i + 1] ?: continue
            val r = gate.assess(display.snapshot(), qrs.snapshot())
            val at = "$name, sample ${i + 1}"
            assertTrue("$at: kSQI ${r.kSqi}, reference ${e[1]}", close(e[1].toDouble(), r.kSqi))
            assertTrue("$at: pSQI ${r.pSqi}, reference ${e[2]}", close(e[2].toDouble(), r.pSqi))
            assertTrue("$at: swing ratio ${r.artifactRatio}, reference ${e[3]}", close(e[3].toDouble(), r.artifactRatio))
            assertEquals("$at: artifact", e[4] == "1", r.artifact)
            assertEquals("$at: verdict", e[5], r.level.name)
            checked++; if (r.artifact) artifacts++
        }
        assertEquals("$name: every reference verdict was compared", expected.size, checked)
        return checked to artifacts
    }

    @Test fun settlingTransients() { val (n, a) = case("tb02_settling"); assertTrue(n > 200 && a > 100) }
    @Test fun burstOfLargeSwings() { val (n, a) = case("tb01_burst"); assertTrue(n > 200 && a > 50) }
    @Test fun cleanRecording() { val (n, a) = case("dual03_finger"); assertTrue(n > 100); assertEquals(0, a) }
    @Test fun addedNoise() { val (n, a) = case("nst_118e00"); assertTrue(n > 100); assertEquals(0, a) }

    // Unit tests run with the module directory (android_app/app) as working dir.
    private val json: String by lazy {
        val f = File("../../sqi_config.json")
        assertTrue("sqi_config.json not found at ${f.absolutePath}", f.exists())
        f.readText()
    }

    private fun num(key: String): Double =
        (Regex("\"$key\"\\s*:\\s*(-?[0-9.]+)").find(json) ?: throw AssertionError("$key missing from sqi_config.json"))
            .groupValues[1].toDouble()

    @Test fun constantsMatchConfig() {
        assertTrue("sqi_config.json is not version ${SignalQuality.VERSION}",
            Regex("\"version\"\\s*:\\s*\"${SignalQuality.VERSION}\"").containsMatchIn(json))
        assertEquals(num("window_s"), SignalQuality.WINDOW_S, 0.0)
        assertEquals(num("window_s"), EcgRingBuffer.SECONDS_SHOWN, 0.0)
        assertEquals(num("k_good"), SignalQuality.K_GOOD, 0.0)
        assertEquals(num("p_good"), SignalQuality.P_GOOD, 0.0)
        assertEquals(num("k_fair"), SignalQuality.K_FAIR, 0.0)
        assertEquals(num("p_fair"), SignalQuality.P_FAIR, 0.0)
        assertEquals(num("block_s"), SignalQuality.BLOCK_S, 0.0)
        assertEquals(num("memory_blocks"), SignalQuality.MEMORY_BLOCKS.toDouble(), 0.0)
        assertEquals(num("ratio_max"), SignalQuality.RATIO_MAX, 0.0)
        assertEquals(num("hold_blocks"), SignalQuality.HOLD_BLOCKS.toDouble(), 0.0)
    }
}
