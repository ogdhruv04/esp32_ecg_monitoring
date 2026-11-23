package com.dhruv.ecgmonitor

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The one-line explanations the report shows on tap are reviewed in
 *  docs/explained/app.md: the app must show exactly that wording. */
class ExplanationsTest {
    @Test fun everyExplanationIsInTheDocVerbatim() {
        val doc = File("../../docs/explained/app.md").readText()
        for ((k, line) in EXPLANATIONS) assertTrue("$k: not in docs/explained/app.md verbatim:\n$line", line in doc)
        for (k in SessionMeasures.ALL_KEYS) assertTrue("$k has no explanation", k in EXPLANATIONS)
    }
}
