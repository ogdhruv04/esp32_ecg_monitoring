package com.dhruv.ecgmonitor

import android.app.Application
import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// A BLE connection the ViewModel can start and throw away. BleEcgClient is
// one; tests substitute a fake (ReconnectTest).
interface BleLink {
    fun start()
    fun stop()
}

private class BleEcgLink(app: Application, listener: BleEcgListener) : BleLink {
    private val client = BleEcgClient(app, listener)
    override fun start() = client.start()
    override fun stop() = client.stop()
}

// Where a Session is. Waiting holds the start until the main screen would show
// a heart rate (GOOD quality), so a session never opens on a signal the app
// itself would not trust; then it records the kind's duration.
sealed interface SessionPhase {
    data object Idle : SessionPhase
    data object Waiting : SessionPhase
    data class Recording(val kind: SessionKind, val startedAtMs: Long, val startedElapsedMs: Long) : SessionPhase
    data class Done(val report: SessionReport) : SessionPhase
}

// Reconnection delays: 1, 2, 4, 8, 16, then 30 s each, back to 1 s once data flows.
class Backoff(private val firstMs: Long = 1_000, private val maxMs: Long = 30_000) {
    private var nextMs = firstMs
    fun next(): Long = nextMs.also { nextMs = minOf(nextMs * 2, maxMs) }
    fun reset() { nextMs = firstMs }
}

// Owns the data source and the pipeline, so both survive rotation. Before this,
// they lived inside setContent: recreating the activity re-requested
// permissions and started a second BLE client next to the first.
class EcgViewModel(app: Application) : AndroidViewModel(app) {
    val pipeline = EcgPipeline()

    // BleEcgClient's own status text, shown on Diagnostics.
    var status by mutableStateOf("Waiting for Bluetooth permissions...")
        private set
    // Bumped on every packet so the UI recomposes and re-reads the pipeline,
    // whose fields are plain (non-Compose-observed) state. Compose coalesces
    // the bumps to at most one recomposition per frame.
    var packetTick by mutableIntStateOf(0)
        private set

    // What the main screen says about the data source. RECEIVING until
    // STALL_MS pass without a packet; the trace is hidden then, leaving the
    // bare grid, rather than freezing the last sweep as if it were live.
    var link by mutableStateOf(Link.SCANNING)
        private set
    // A fix for NOT_CONNECTED when the cause is known ("Turn on Bluetooth").
    var linkFix by mutableStateOf<String?>(null)
        private set
    // True from losing a live stream until data flows again. Only then is
    // "Ring not connected" an alert; before the first connection it is not.
    var dropped by mutableStateOf(false)
        private set
    private var everReceived = false
    private var lastPacketAt = 0L

    // Arrival rate over the last RATE_WINDOW_MS, from packet timestamps.
    // Null until the window has filled.
    var sampleRate by mutableStateOf<Double?>(null)
        private set
    private val arrivals = ArrayDeque<Pair<Long, Int>>()

    var replayFile by mutableStateOf<String?>(null)
        private set
    private var replayJob: Job? = null

    private val prefs = app.getSharedPreferences("display", Application.MODE_PRIVATE)
    // A stored choice wins; the default applies only to a fresh install.
    var gainMmPerMv by mutableIntStateOf(
        prefs.getInt(KEY_GAIN, DEFAULT_GAIN_MM_PER_MV).takeIf { it in GAINS_MM_PER_MV } ?: DEFAULT_GAIN_MM_PER_MV
    )
        private set
    var researchMode by mutableStateOf(prefs.getBoolean(KEY_RESEARCH, false))
        private set
    var showFiltered by mutableStateOf(true)

    fun cycleGain() {
        gainMmPerMv = nextGain(gainMmPerMv)
        prefs.edit().putInt(KEY_GAIN, gainMmPerMv).apply()
    }

    // ------------------------------------------------------------- sessions

    var sessionPhase by mutableStateOf<SessionPhase>(SessionPhase.Idle)
        private set
    // Opened on first use, so tests that never touch history never open it.
    internal var storeFactory: () -> SessionStore = { SessionStore(SessionDatabase.open(getApplication())) }
    private val store by lazy { storeFactory() }
    val history: Flow<List<SessionReport>> get() = store.all
    private var endedEarly = false
    // The kind chosen on the Session screen; used when the clock starts.
    var sessionKind by mutableStateOf(SessionKind.STANDARD)

    fun startSession() {
        if (sessionPhase is SessionPhase.Idle || sessionPhase is SessionPhase.Done) sessionPhase = SessionPhase.Waiting
    }

    fun cancelSession() {
        pipeline.cancelSession()
        sessionPhase = SessionPhase.Idle
    }

    fun closeReport() {
        if (sessionPhase is SessionPhase.Done) sessionPhase = SessionPhase.Idle
    }

    fun deleteSession(id: Long) {
        viewModelScope.launch { store.delete(id) }
    }

    private fun currentHeadline() = pipeline.let {
        headline(link, linkFix, dropped, it.qualityReady, it.signalQuality.level, it.heartRate, it.mainsShare)
    }

    private fun sessionEnded(rec: SessionRecorder) {
        val r = sessionPhase as? SessionPhase.Recording ?: return
        val report = SessionReport.from(rec, rec.report(r.kind), r.kind, r.startedAtMs, replayFile, endedEarly)
        endedEarly = false
        sessionPhase = SessionPhase.Done(report)
        Log.i(TAG, "session done: ${report.beats} beats, lost ${report.samplesLost} samples, " +
            report.measures.entries.joinToString(" ") { (k, m) -> "$k=${m.value?.let { "%.4g".format(it) } ?: "-"}" })
        viewModelScope.launch {
            val id = store.save(report)
            val now = sessionPhase
            if (now is SessionPhase.Done && now.report === report) sessionPhase = SessionPhase.Done(report.copy(id = id))
        }
    }

    fun updateResearchMode(on: Boolean) {
        researchMode = on
        prefs.edit().putBoolean(KEY_RESEARCH, on).apply()
    }

    // ------------------------------------------------------------- BLE link

    // Tests swap this for a fake before startBle().
    internal var linkFactory: (BleEcgListener) -> BleLink = { BleEcgLink(getApplication(), it) }
    private var ble: BleLink? = null
    private var currentListener: BleEcgListener? = null
    private var bleWanted = false
    private var linkStartedAt = 0L
    private val backoff = Backoff()
    private var reconnectJob: Job? = null
    // Set when a live stream is lost; the next packet then starts a new
    // stream in the pipeline (see EcgPipeline.breakStream).
    private var streamBroken = false

    // Each client gets its own listener, ignored once that client is replaced,
    // so a late callback from a dead connection can't act on the new one.
    private fun listenerForNewLink(): BleEcgListener = object : BleEcgListener {
        override fun onStatus(status: String) { if (this === currentListener) handleStatus(status) }
        override fun onPacket(packet: EcgPacket) { if (this === currentListener) handlePacket(packet) }
    }

    private fun handleStatus(s: String) {
        status = s
        Log.i(TAG, "ble status: $s")
        val (mapped, fix) = linkFromStatus(s) ?: return
        when (mapped) {
            Link.NOT_CONNECTED -> linkFailed(fix)
            // Scanning or connecting. While recovering from a drop the screen
            // keeps saying the ring is lost until data actually returns.
            else -> if (link != Link.RECEIVING && !dropped) setLink(Link.SCANNING, null)
        }
    }

    private fun handlePacket(packet: EcgPacket) {
        val now = SystemClock.elapsedRealtime()
        if (streamBroken) {
            val missed = ((now - lastPacketAt) * EcgFilter.ECG_SAMPLE_RATE / 1000).toInt()
            pipeline.breakStream(missed)
            streamBroken = false
            Log.i(TAG, "stream resumed after ${now - lastPacketAt} ms; marked $missed samples as lost")
        }
        pipeline.onPacket(packet)
        if (sessionPhase == SessionPhase.Waiting && link == Link.RECEIVING && currentHeadline() is Headline.Rate) {
            pipeline.startSession(sessionKind.durationS)
            sessionPhase = SessionPhase.Recording(sessionKind, System.currentTimeMillis(), now)
            Log.i(TAG, "session started at sample ${pipeline.session?.s0}")
        }
        packetTick++
        lastPacketAt = now
        everReceived = true
        dropped = false
        backoff.reset()
        setLink(Link.RECEIVING, null)
        arrivals.addLast(now to packet.samples.size)
        while (now - arrivals.first().first > RATE_WINDOW_MS) arrivals.removeFirst()
        val span = now - arrivals.first().first
        sampleRate = if (span >= RATE_WINDOW_MS * 0.9)
            // Samples after the first arrival, over the time since it.
            (arrivals.sumOf { it.second } - arrivals.first().second) * 1000.0 / span
        else null
    }

    private fun linkFailed(fix: String?) {
        if (everReceived && !dropped) { dropped = true; streamBroken = true }
        setLink(Link.NOT_CONNECTED, if (dropped) "Reconnecting…" else fix)
        scheduleReconnect()
    }

    private fun scheduleReconnect() {
        if (!bleWanted || reconnectJob != null) return
        // BleEcgClient leaves its GATT open after a disconnect; close it.
        ble?.stop()
        ble = null
        currentListener = null
        val delayMs = backoff.next()
        Log.i(TAG, "reconnecting in $delayMs ms")
        reconnectJob = viewModelScope.launch {
            delay(delayMs)
            reconnectJob = null
            startLink()
        }
    }

    private fun startLink() {
        val l = listenerForNewLink()
        currentListener = l
        linkStartedAt = SystemClock.elapsedRealtime()
        ble = linkFactory(l).also { it.start() }
    }

    private fun setLink(l: Link, fix: String?) {
        if (l != link) Log.i(TAG, "link $link -> $l")
        link = l
        linkFix = fix
    }

    init {
        pipeline.onSessionEnd = ::sessionEnded
        viewModelScope.launch {
            var lastStats = 0L
            while (true) {
                delay(250)
                val now = SystemClock.elapsedRealtime()
                if (link == Link.RECEIVING && now - lastPacketAt > STALL_MS) {
                    sampleRate = null
                    arrivals.clear()
                    if (replayFile != null) {
                        setLink(if (replayJob?.isActive == false) Link.REPLAY_FINISHED else Link.NOT_CONNECTED, null)
                    } else {
                        dropped = true
                        streamBroken = true
                        setLink(Link.NOT_CONNECTED, "Reconnecting…")
                    }
                }
                // Packets stopped but no "Disconnected" came: restart the link.
                if (bleWanted && dropped && reconnectJob == null &&
                    now - lastPacketAt > SILENT_RESTART_MS && now - linkStartedAt > SILENT_RESTART_MS
                ) {
                    Log.i(TAG, "no data for ${now - lastPacketAt} ms on an open link; restarting it")
                    scheduleReconnect()
                }
                // A session whose stream stopped for good: close it with what it has.
                val ph = sessionPhase
                if (ph is SessionPhase.Recording &&
                    now - ph.startedElapsedMs > ((ph.kind.durationS + SessionConfig.TAIL_S) * 1000).toLong() + SESSION_GRACE_MS
                ) {
                    Log.i(TAG, "session stream stopped; ending it early")
                    endedEarly = true
                    pipeline.endSessionEarly()
                }
                if (link == Link.RECEIVING && now - lastStats >= STATS_EVERY_MS) {
                    lastStats = now
                    logStats()
                }
            }
        }
    }

    // One line every STATS_EVERY_MS while receiving, for the live test log.
    private fun logStats() {
        val p = pipeline
        val sq = p.signalQuality
        Log.i(
            TAG,
            "stats packets=${p.packetsSeen} lost=${p.packetsLost} skipped=${p.samplesSkipped} " +
                "breaks=${p.streamBreaks} rate=${sampleRate?.let { "%.1f".format(it) } ?: "-"} " +
                "quality=${if (p.qualityReady) sq.level else "pending"} kSQI=${"%.1f".format(sq.kSqi)} " +
                "pSQI=${"%.2f".format(sq.pSqi)} mains=${"%.1f".format(100 * p.mainsShare)}% " +
                "headline=${headline(link, linkFix, dropped, p.qualityReady, sq.level, p.heartRate, p.mainsShare)}"
        )
    }

    // Safe to call again after rotation; only the first call starts a client.
    fun startBle() {
        if (bleWanted || replayJob != null) return
        bleWanted = true
        status = "Permissions granted, starting scan..."
        setLink(Link.SCANNING, null)
        startLink()
    }

    fun permissionsDenied() {
        status = "Bluetooth permissions denied - cannot scan/connect"
        Log.i(TAG, "ble status: $status")
        setLink(Link.NOT_CONNECTED, "Allow Bluetooth access in Settings")
    }

    // Release builds bundle no captures, so a replay request is ignored there.
    val replayAvailable: Boolean
        get() = getApplication<Application>().assets.list(REPLAY_DIR).orEmpty().isNotEmpty()

    // Plays a bundled capture (debug builds only; see copyReplayCaptures in
    // app/build.gradle.kts) through the same path BLE uses, in real time.
    // Lost packets keep their time hole. `name` is an asset name, with or
    // without ".csv". Replaces BLE for the life of the ViewModel.
    fun startReplay(name: String) {
        if (bleWanted || replayJob != null) return
        val app = getApplication<Application>()
        val file = if (name.endsWith(".csv")) name else "$name.csv"
        val available = app.assets.list(REPLAY_DIR).orEmpty()
        if (file !in available) {
            status = "Replay '$name' not found. Bundled: " +
                available.joinToString { it.removeSuffix(".csv") }.ifEmpty { "none (release build)" }
            setLink(Link.NOT_CONNECTED, null)
            return
        }
        replayFile = file
        Log.i(TAG, "replay $file")
        replayJob = viewModelScope.launch {
            status = "Replay $file: loading"
            val packets = withContext(Dispatchers.IO) {
                app.assets.open("$REPLAY_DIR/$file").use { CaptureReplay.packets(it) }
            }
            status = "Replay $file"
            val start = SystemClock.elapsedRealtime()
            for (p in packets) {
                val due = start + (p.sampleOffset * 1000 / EcgFilter.ECG_SAMPLE_RATE).toLong()
                delay(due - SystemClock.elapsedRealtime())
                handlePacket(p.packet)
            }
            status = "Replay $file: finished"
        }
    }

    override fun onCleared() {
        bleWanted = false
        reconnectJob?.cancel()
        ble?.stop()
    }

    companion object {
        const val TAG = "EcgMonitor"
        const val REPLAY_DIR = "replay"
        private const val KEY_GAIN = "gain_mm_per_mv"
        private const val KEY_RESEARCH = "research_mode"
        // Packets normally arrive every 6/256 s (about 23 ms); a full second of
        // silence means the stream has stopped, not that one packet was late.
        const val STALL_MS = 1_000L
        // After a stall with no disconnect callback, wait this long for one
        // before restarting the link ourselves. The firmware asks for a 1.8 s
        // supervision timeout (updateConnParams in sketch.ino), so a real drop
        // normally reports well inside it.
        const val SILENT_RESTART_MS = 8_000L
        private const val RATE_WINDOW_MS = 5_000L
        private const val STATS_EVERY_MS = 10_000L
        // How long past its nominal end a session may wait for samples (a
        // reconnection) before it is closed with what it has.
        const val SESSION_GRACE_MS = 15_000L
    }
}

// Maps BleEcgClient's status strings onto the main screen's link states.
// Those strings are its only signal, so this has to track them; an unknown
// one leaves the state as it was.
internal fun linkFromStatus(status: String): Pair<Link, String?>? = when {
    status.startsWith("Scanning") || status.startsWith("Found") || status.startsWith("Connected") ||
        status.startsWith("Subscribed") || status.startsWith("Permissions granted") -> Link.SCANNING to null
    status.startsWith("Bluetooth not available") -> Link.NOT_CONNECTED to "Turn on Bluetooth"
    status.startsWith("Disconnected") || status.startsWith("ECG characteristic not found") ||
        status.startsWith("Scan failed") -> Link.NOT_CONNECTED to null
    else -> null
}
