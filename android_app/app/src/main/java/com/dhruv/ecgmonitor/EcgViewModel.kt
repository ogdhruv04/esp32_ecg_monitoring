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

    var status by mutableStateOf("Waiting for Bluetooth permissions...")
        private set
    // Bumped on every packet so the UI recomposes and re-reads the pipeline,
    // whose fields are plain (non-Compose-observed) state. Compose coalesces
    // the bumps to at most one recomposition per frame.
    var packetTick by mutableIntStateOf(0)
        private set

    // False until the first packet, and again after STALL_MS without one; the
    // trace is hidden then, leaving the bare grid, rather than freezing the
    // last sweep on screen as if it were live.
    var receiving by mutableStateOf(false)
        private set
    private var lastPacketAt = 0L

    private val prefs = app.getSharedPreferences("display", Application.MODE_PRIVATE)
    var gainMmPerMv by mutableIntStateOf(
        prefs.getInt(KEY_GAIN, GAINS_MM_PER_MV[0]).takeIf { it in GAINS_MM_PER_MV } ?: GAINS_MM_PER_MV[0]
    )
        private set

    fun cycleGain() {
        gainMmPerMv = nextGain(gainMmPerMv)
        prefs.edit().putInt(KEY_GAIN, gainMmPerMv).apply()
    }

    private var bleClient: BleEcgClient? = null

    private val listener = object : BleEcgListener {
        override fun onStatus(status: String) { this@EcgViewModel.status = status }
        override fun onPacket(packet: EcgPacket) {
            pipeline.onPacket(packet)
            packetTick++
            lastPacketAt = SystemClock.elapsedRealtime()
            receiving = true
        }
    }

    init {
        viewModelScope.launch {
            while (true) {
                delay(250)
                if (receiving && SystemClock.elapsedRealtime() - lastPacketAt > STALL_MS) receiving = false
            }
        }
    }

    private var replayJob: Job? = null
    val isReplay: Boolean get() = replayJob != null

    // Safe to call again after rotation; only the first call starts a client.
    fun startBle() {
        if (bleClient != null || replayJob != null) return
        status = "Permissions granted, starting scan..."
        bleClient = BleEcgClient(getApplication(), listener).also { it.start() }
    }

    fun permissionsDenied() {
        status = "Bluetooth permissions denied - cannot scan/connect"
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
            return
        }
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
        // Packets normally arrive every 6/256 s (about 23 ms); a full second of
        // silence means the stream has stopped, not that one packet was late.
        private const val STALL_MS = 1000L
    }
}
