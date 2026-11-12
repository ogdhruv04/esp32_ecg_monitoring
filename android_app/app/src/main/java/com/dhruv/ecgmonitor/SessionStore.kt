package com.dhruv.ecgmonitor

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Embedded
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Relation
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import com.dhruv.ecgmonitor.algorithms.AlgConfig
import com.dhruv.ecgmonitor.algorithms.Result
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

// ------------------------------------------------------------- report model

/** One measure of a report: a value, or null with the reason it was withheld. */
data class Measure(
    val value: Double?,
    val unit: String,
    val withheld: String?,
    val nUsed: Int,
    val validS: Double,
    val coverage: Double,
    // Breathing rate only: range of the per-window rates behind the median.
    val min: Double? = null,
    val max: Double? = null,
) {
    companion object {
        fun of(r: Result) = Measure(r.value, r.unit, r.withheld, r.nUsed, r.validS, r.coverage, r.extra["min"], r.extra["max"])
    }
}

/**
 * Measures that later workstreams will add (docs/MIDTERM_PLAN.md): rhythm
 * check, ectopic count, motion and arousal against the wearer's baseline.
 * Stored and carried through now, always null, and never drawn: the report
 * shows a slot only once it has a validated algorithm behind it
 * (SessionUi.kt, PENDING_SLOTS_VISIBLE).
 */
data class PendingSlots(
    val rhythm: String? = null,
    val ectopicCount: Int? = null,
    val motionShare: Double? = null,
    val arousal: Double? = null,
)

data class SessionReport(
    val id: Long = 0,
    val startedAtMs: Long,
    val durationS: Double,
    /** null = live; otherwise the replayed file. */
    val replayFile: String?,
    val beats: Int,
    val samplesLost: Long,
    val goodShare: Double,
    /** True when the stream stopped and the session was closed before its end. */
    val endedEarly: Boolean,
    val measures: Map<String, Measure>,
    val pending: PendingSlots = PendingSlots(),
    val versions: String = VERSIONS,
) {
    companion object {
        const val VERSIONS = "session ${SessionConfig.VERSION} · algorithms ${AlgConfig.VERSION} · detector tp2.1"

        fun from(
            rec: SessionRecorder, m: SessionMeasures, startedAtMs: Long, replayFile: String?, endedEarly: Boolean,
        ) = SessionReport(
            startedAtMs = startedAtMs,
            durationS = (rec.s1 - rec.s0) / EcgFilter.ECG_SAMPLE_RATE,
            replayFile = replayFile,
            beats = m.beats,
            samplesLost = rec.samplesLost,
            goodShare = rec.qualityShare(SignalQuality.Level.GOOD),
            endedEarly = endedEarly,
            measures = m.results.mapValues { Measure.of(it.value) },
        )
    }
}

// --------------------------------------------------------------------- Room

@Entity(tableName = "sessions")
data class SessionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val startedAtMs: Long,
    val durationS: Double,
    val replayFile: String?,
    val beats: Int,
    val samplesLost: Long,
    val goodShare: Double,
    val endedEarly: Boolean,
    val versions: String,
    // Pending slots (PendingSlots): null until their algorithms exist.
    val rhythm: String?,
    val ectopicCount: Int?,
    val motionShare: Double?,
    val arousal: Double?,
)

@Entity(
    tableName = "measures",
    primaryKeys = ["sessionId", "key"],
    foreignKeys = [ForeignKey(
        entity = SessionEntity::class, parentColumns = ["id"], childColumns = ["sessionId"],
        onDelete = ForeignKey.CASCADE,
    )],
)
data class MeasureEntity(
    val sessionId: Long,
    val key: String,
    val value: Double?,
    val unit: String,
    val withheld: String?,
    val nUsed: Int,
    val validS: Double,
    val coverage: Double,
    val min: Double?,
    val max: Double?,
)

data class SessionWithMeasures(
    @Embedded val session: SessionEntity,
    @Relation(parentColumn = "id", entityColumn = "sessionId") val measures: List<MeasureEntity>,
)

@Dao
abstract class SessionDao {
    @Insert abstract suspend fun insertSession(s: SessionEntity): Long
    @Insert abstract suspend fun insertMeasures(m: List<MeasureEntity>)

    @Transaction
    open suspend fun insert(s: SessionEntity, m: (Long) -> List<MeasureEntity>): Long {
        val id = insertSession(s)
        insertMeasures(m(id))
        return id
    }

    @Transaction
    @Query("SELECT * FROM sessions ORDER BY startedAtMs DESC")
    abstract fun observeAll(): Flow<List<SessionWithMeasures>>

    @Query("DELETE FROM sessions WHERE id = :id")
    abstract suspend fun delete(id: Long)
}

@Database(entities = [SessionEntity::class, MeasureEntity::class], version = 1, exportSchema = true)
abstract class SessionDatabase : RoomDatabase() {
    abstract fun sessions(): SessionDao

    companion object {
        fun open(context: Context): SessionDatabase =
            Room.databaseBuilder(context, SessionDatabase::class.java, "sessions.db").build()
        fun inMemory(context: Context): SessionDatabase =
            Room.inMemoryDatabaseBuilder(context, SessionDatabase::class.java).allowMainThreadQueries().build()
    }
}

/** Reports in and out of Room. */
class SessionStore(private val db: SessionDatabase) {
    val all: Flow<List<SessionReport>> = db.sessions().observeAll().map { rows -> rows.map(::toReport) }

    suspend fun save(r: SessionReport): Long = db.sessions().insert(
        SessionEntity(
            startedAtMs = r.startedAtMs, durationS = r.durationS, replayFile = r.replayFile, beats = r.beats,
            samplesLost = r.samplesLost, goodShare = r.goodShare, endedEarly = r.endedEarly, versions = r.versions,
            rhythm = r.pending.rhythm, ectopicCount = r.pending.ectopicCount,
            motionShare = r.pending.motionShare, arousal = r.pending.arousal,
        )
    ) { id ->
        r.measures.map { (k, m) ->
            MeasureEntity(id, k, m.value, m.unit, m.withheld, m.nUsed, m.validS, m.coverage, m.min, m.max)
        }
    }

    suspend fun delete(id: Long) = db.sessions().delete(id)

    private fun toReport(row: SessionWithMeasures): SessionReport {
        val s = row.session
        val byKey = row.measures.associateBy { it.key }
        return SessionReport(
            id = s.id, startedAtMs = s.startedAtMs, durationS = s.durationS, replayFile = s.replayFile,
            beats = s.beats, samplesLost = s.samplesLost, goodShare = s.goodShare, endedEarly = s.endedEarly,
            // In report order, whatever order the rows came back in.
            measures = SessionMeasures.KEYS.mapNotNull { k ->
                byKey[k]?.let { k to Measure(it.value, it.unit, it.withheld, it.nUsed, it.validS, it.coverage, it.min, it.max) }
            }.toMap(),
            pending = PendingSlots(s.rhythm, s.ectopicCount, s.motionShare, s.arousal),
            versions = s.versions,
        )
    }
}
