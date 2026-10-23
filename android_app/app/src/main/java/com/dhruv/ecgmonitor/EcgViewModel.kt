package com.dhruv.ecgmonitor

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel

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

    private var bleClient: BleEcgClient? = null

    private val listener = object : BleEcgListener {
        override fun onStatus(status: String) { this@EcgViewModel.status = status }
        override fun onPacket(packet: EcgPacket) {
            pipeline.onPacket(packet)
            packetTick++
        }
    }

    // Safe to call again after rotation; only the first call starts a client.
    fun startBle() {
        if (bleClient != null) return
        status = "Permissions granted, starting scan..."
        bleClient = BleEcgClient(getApplication(), listener).also { it.start() }
    }

    fun permissionsDenied() {
        status = "Bluetooth permissions denied - cannot scan/connect"
    }

    override fun onCleared() {
        bleClient?.stop()
    }
}
