package com.dhruv.ecgmonitor

import com.dhruv.ecgmonitor.algorithms.median

/** Earlier live sessions needed before a report compares with "your usual". */
const val BASELINE_MIN_SESSIONS = 3

/** The median and range of one measure over earlier sessions. */
data class Usual(val median: Double, val min: Double, val max: Double, val n: Int)

/** [sessions]: earlier live sessions. [usual]: per summary measure, only when
 *  at least BASELINE_MIN_SESSIONS of them have a value for it. */
data class Baseline(val sessions: Int, val usual: Map<String, Usual>) {
    val ready: Boolean get() = sessions >= BASELINE_MIN_SESSIONS
}

/**
 * The wearer's usual for [report]'s summary measures: every stored session
 * that started before it and was recorded live. Replays never count: they
 * are someone else's data, or ours from another day, replayed for testing.
 */
fun baselineFor(report: SessionReport, history: List<SessionReport>): Baseline {
    val earlier = history.filter { it.replayFile == null && it.startedAtMs < report.startedAtMs }
    val usual = SUMMARY_KEYS.mapNotNull { k ->
        val v = earlier.mapNotNull { it.measures[k]?.value }
        if (v.size < BASELINE_MIN_SESSIONS) null
        else k to Usual(median(v.toDoubleArray()), v.min(), v.max(), v.size)
    }.toMap()
    return Baseline(earlier.size, usual)
}
