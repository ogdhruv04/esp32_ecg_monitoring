package com.dhruv.ecgmonitor.algorithms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import java.io.File
import kotlin.math.abs

/** Reads the fixtures make_session_fixtures.py writes, and compares Results. */
object Fixtures {
    fun resource(path: String): String {
        val url = javaClass.classLoader!!.getResource(path)
        assertNotNull("missing fixture $path - run make_session_fixtures.py", url)
        return url!!.readText()
    }

    /** A file at the repository root (unit tests run in android_app/app). */
    fun repoFile(name: String): String {
        val f = File("../../$name")
        assertTrue("$name not found at ${f.absolutePath}", f.exists())
        return f.readText()
    }

    fun num(s: String): Double = if (s == "nan") Double.NaN else s.toDouble()

    class Expected(val key: String, val value: Double, val withheld: String, val nUsed: Int,
                   val validS: Double, val spanS: Double, val coverage: Double)

    fun results(path: String): List<Expected> = resource(path).lines().drop(1).filter { it.isNotBlank() }.map {
        val c = it.split('\t')
        Expected(c[0], num(c[1]), c[2], c[3].toInt(), num(c[4]), num(c[5]), num(c[6]))
    }

    /** Same value to 1e-9 relative (or absolute below 1), same reason word
     *  for word, same counts. */
    fun assertSame(label: String, e: Expected, r: Result) {
        if (e.value.isNaN()) {
            assertEquals("$label: phone shows ${r.value} where Python withholds", null, r.value)
            assertEquals("$label withheld reason", e.withheld, r.withheld)
        } else {
            assertNotNull("$label: phone withholds (${r.withheld}) where Python gives ${e.value}", r.value)
            close("$label value", e.value, r.value!!)
            assertEquals("$label withheld", null, r.withheld)
        }
        assertEquals("$label n_used", e.nUsed, r.nUsed)
        close("$label valid_s", e.validS, r.validS)
        close("$label span_s", e.spanS, r.spanS)
        close("$label coverage", e.coverage, r.coverage)
    }

    fun close(label: String, expected: Double, actual: Double) {
        if (expected.isNaN()) { assertTrue("$label: expected nan, got $actual", actual.isNaN()); return }
        val tol = 1e-9 * maxOf(1.0, abs(expected))
        assertTrue("$label: python $expected, kotlin $actual", abs(expected - actual) <= tol)
    }
}
