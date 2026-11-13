package com.dhruv.ecgmonitor

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** A report survives Room unchanged: every measure, every withheld reason,
 *  the pending slots, and the order of the report. */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class SessionStoreTest {
    @Test fun reportRoundTrips() = runBlocking {
        val db = SessionDatabase.inMemory(ApplicationProvider.getApplicationContext<Context>())
        val store = SessionStore(db)
        val (_, rec) = SessionReplay.run(SessionReplay.capturePackets("20261027_174352_testboard02.csv"), 20.0)
        val report = SessionReplay.report(rec!!, 1_794_000_000_000, "tb02.csv")
        assertTrue("some measures withheld, some shown", report.measures.values.any { it.value == null } &&
            report.measures.values.any { it.value != null })
        val id = store.save(report)
        val back = store.all.first().single()
        assertEquals(report.copy(id = id), back)
        assertEquals(SessionMeasures.KEYS, back.measures.keys.toList())
        assertEquals(SessionKind.STANDARD, back.kind)

        store.delete(id)
        assertEquals(0, store.all.first().size)
        db.close()
    }
}
