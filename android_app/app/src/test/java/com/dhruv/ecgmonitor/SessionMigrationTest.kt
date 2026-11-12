package com.dhruv.ecgmonitor

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** Schema 1 (12 Nov 2026, before session kinds) migrates to 2 with its rows
 *  kept and marked standard. Checked against the exported schemas in app/schemas. */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class SessionMigrationTest {
    @get:Rule val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), SessionDatabase::class.java)

    @Test fun oneToTwoKeepsSessions() {
        helper.createDatabase("migrate.db", 1).apply {
            execSQL(
                "INSERT INTO sessions (id, startedAtMs, durationS, replayFile, beats, samplesLost, goodShare, endedEarly, versions) " +
                    "VALUES (1, 1000, 180.0, NULL, 200, 0, 0.9, 0, 'v1')"
            )
            execSQL(
                "INSERT INTO measures (sessionId, key, value, unit, withheld, nUsed, validS, coverage, min, max) " +
                    "VALUES (1, 'hr', 70.0, 'bpm', NULL, 199, 180.0, 1.0, NULL, NULL)"
            )
            close()
        }
        val db = helper.runMigrationsAndValidate("migrate.db", 2, true, SessionDatabase.MIGRATION_1_2)
        db.query("SELECT kind, beats FROM sessions WHERE id = 1").use {
            it.moveToFirst()
            assertEquals("standard", it.getString(0))
            assertEquals(200, it.getInt(1))
        }
        db.query("SELECT COUNT(*) FROM measures").use { it.moveToFirst(); assertEquals(1, it.getInt(0)) }
    }
}
