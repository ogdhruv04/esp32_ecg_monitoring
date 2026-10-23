package com.dhruv.ecgmonitor

import android.Manifest
import android.app.Application
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanResult
import org.robolectric.Shadows.shadowOf

// Plays the ring through Robolectric's Bluetooth shadows, so tests run the
// real BleEcgClient: it advertises, accepts a connection, notifies packets,
// and drops off.
internal class SimulatedRing(app: Application) {
    private val adapter = app.getSystemService(BluetoothManager::class.java).adapter
    val device = adapter.getRemoteDevice("24:58:7C:00:00:01")

    init {
        shadowOf(app).grantPermissions(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        shadowOf(adapter).setEnabled(true)
        shadowOf(device).setName("ESP32-ECG")
    }

    private val scanner get() = shadowOf(adapter.bluetoothLeScanner)

    // Scans still running; a leaked scan would show up here.
    val activeScans: Int get() = scanner.scanCallbacks.size

    // Every GATT the client has opened to the ring, oldest first.
    val gatts: List<BluetoothGatt> get() = shadowOf(device).bluetoothGatts

    val openGatts: Int get() = gatts.count { !shadowOf(it).isClosed }

    @Suppress("DEPRECATION")
    fun advertise() = scanner.scanCallbacks.toList().forEach {
        it.onScanResult(1, ScanResult(device, null, -50, 0L))
    }

    fun connect() = shadowOf(device).simulateGattConnectionChange(BluetoothGatt.GATT_SUCCESS, BluetoothProfile.STATE_CONNECTED)

    // The shadow doesn't call back after discoverServices(); deliver it the
    // way the stack would. The shadow GATT has no ECG service.
    fun finishDiscovery() = gatts.last().let { shadowOf(it).gattCallback.onServicesDiscovered(it, BluetoothGatt.GATT_SUCCESS) }

    // Status 8 is the supervision timeout a powered-off ring produces.
    fun drop() = shadowOf(device).simulateGattConnectionChange(8, BluetoothProfile.STATE_DISCONNECTED)

    // One BLE notification in the firmware's layout: [seq][count=6][6 x 3-byte LE samples].
    @Suppress("DEPRECATION")
    fun notifyPacket(seq: Int) {
        val g = gatts.last()
        val bytes = ByteArray(20).also { it[0] = seq.toByte(); it[1] = 6 }
        val ch = BluetoothGattCharacteristic(ECG_CHAR_UUID, BluetoothGattCharacteristic.PROPERTY_NOTIFY, 0)
        ch.value = bytes
        shadowOf(g).gattCallback.onCharacteristicChanged(g, ch)
    }
}
