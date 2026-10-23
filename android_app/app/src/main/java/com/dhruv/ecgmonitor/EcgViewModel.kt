package com.dhruv.ecgmonitor

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// Owns the data source and the pipeline, so both survive rotation. Before this,
// they lived inside setContent: recreating the activity re-requested
// permissions and started a second BLE client next to the first.
class EcgViewModel(app: Application) : AndroidViewModel(app) {
    val pipeline = EcgPipeline()

    // BleEcgClient's own status text, shown verbatim on Diagnostics.
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

    fun updateResearchMode(on: Boolean) {
        researchMode = on
        prefs.edit().putBoolean(KEY_RESEARCH, on).apply()
    }

    private var bleClient: BleEcgClient? = null

    private val listener = object : BleEcgListener {
        override fun onStatus(status: String) {
            this@EcgViewModel.status = status
            val (mapped, fix) = linkFromStatus(status) ?: return
            // A late "connecting" message must not hide a live stream.
            if (link == Link.RECEIVING && mapped == Link.SCANNING) return
            link = mapped
            linkFix = fix
        }
        override fun onPacket(packet: EcgPacket) {
            pipeline.onPacket(packet)
            packetTick++
            val now = SystemClock.elapsedRealtime()
            lastPacketAt = now
            link = Link.RECEIVING
            linkFix = null
            arrivals.addLast(now to packet.samples.size)
            while (now - arrivals.first().first > RATE_WINDOW_MS) arrivals.removeFirst()
            val span = now - arrivals.first().first
            sampleRate = if (span >= RATE_WINDOW_MS * 0.9)
                // Samples after the first arrival, over the time since it.
                (arrivals.sumOf { it.second } - arrivals.first().second) * 1000.0 / span
            else null
        }
    }

    init {
        viewModelScope.launch {
            while (true) {
                delay(250)
                if (link == Link.RECEIVING && SystemClock.elapsedRealtime() - lastPacketAt > STALL_MS) {
                    link = if (replayFile != null && replayJob?.isActive == false) Link.REPLAY_FINISHED else Link.NOT_CONNECTED
                    sampleRate = null
                    arrivals.clear()
                }
            }
        }
    }

    // Safe to call again after rotation; only the first call starts a client.
    fun startBle() {
        if (bleClient != null || replayJob != null) return
        status = "Permissions granted, starting scan..."
        link = Link.SCANNING
        bleClient = BleEcgClient(getApplication(), listener).also { it.start() }
    }

    fun permissionsDenied() {
        status = "Bluetooth permissions denied - cannot scan/connect"
        link = Link.NOT_CONNECTED
        linkFix = "Allow Bluetooth access in Settings"
    }

    // Plays a bundled capture (debug builds only; see copyReplayCaptures in
    // app/build.gradle.kts) through the same listener BLE uses, in real time.
    // Lost packets keep their time hole. `name` is an asset name, with or
    // without ".csv". Replaces BLE for the life of the ViewModel.
    fun startReplay(name: String) {
        if (bleClient != null || replayJob != null) return
        val app = getApplication<Application>()
        val file = if (name.endsWith(".csv")) name else "$name.csv"
        val available = app.assets.list(REPLAY_DIR).orEmpty()
        if (file !in available) {
            status = "Replay '$name' not found. Bundled: " +
                available.joinToString { it.removeSuffix(".csv") }.ifEmpty { "none (release build)" }
            link = Link.NOT_CONNECTED
            return
        }
        replayFile = file
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
                listener.onPacket(p.packet)
            }
            status = "Replay $file: finished"
        }
    }

    override fun onCleared() {
        bleClient?.stop()
    }

    companion object {
        const val REPLAY_DIR = "replay"
        private const val KEY_GAIN = "gain_mm_per_mv"
        private const val KEY_RESEARCH = "research_mode"
        // Packets normally arrive every 6/256 s (about 23 ms); a full second of
        // silence means the stream has stopped, not that one packet was late.
        private const val STALL_MS = 1000L
        private const val RATE_WINDOW_MS = 5000L
    }
}

// Maps BleEcgClient's status strings onto the main screen's link states.
// Those strings are its only signal, so this has to track them; an unknown
// one leaves the state as it was.
internal fun linkFromStatus(status: String): Pair<Link, String?>? = when {
    status.startsWith("Scanning") || status.startsWith("Connected") ||
        status.startsWith("Subscribed") || status.startsWith("Permissions granted") -> Link.SCANNING to null
    status.startsWith("Bluetooth not available") -> Link.NOT_CONNECTED to "Turn on Bluetooth"
    status.startsWith("Disconnected") || status.startsWith("ECG characteristic not found") -> Link.NOT_CONNECTED to null
    else -> null
}
