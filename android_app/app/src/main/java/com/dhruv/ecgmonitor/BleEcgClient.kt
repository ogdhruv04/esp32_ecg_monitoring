package com.dhruv.ecgmonitor

import android.annotation.SuppressLint
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import java.util.UUID

val ECG_SERVICE_UUID: UUID = UUID.fromString("e54b0001-67f5-479e-8711-b3b99198ce6c")
val ECG_CHAR_UUID: UUID = UUID.fromString("e54b0002-67f5-479e-8711-b3b99198ce6c")
private val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

data class EcgPacket(val seq: Int, val count: Int, val samples: IntArray)

interface BleEcgListener {
    fun onStatus(status: String)
    fun onPacket(packet: EcgPacket)
}

// Caller must have already requested BLUETOOTH_SCAN/BLUETOOTH_CONNECT before calling start().
@SuppressLint("MissingPermission")
class BleEcgClient(private val context: Context, private val listener: BleEcgListener) {

    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private var gatt: BluetoothGatt? = null
    private var scanning = false

    // BLE callbacks land on a background Binder thread, not the main thread -
    // Compose state must only be touched from the UI thread, so every listener
    // call is posted through here rather than invoked directly.
    private fun postStatus(s: String) = mainHandler.post { listener.onStatus(s) }
    private fun postPacket(p: EcgPacket) = mainHandler.post { listener.onPacket(p) }

    fun start() {
        val scanner = bluetoothManager.adapter?.bluetoothLeScanner
        if (scanner == null) {
            postStatus("Bluetooth not available/enabled")
            return
        }
        // Scan unfiltered and match manually in onScanResult instead of using an
        // OS-level ScanFilter - some OEM BLE stacks (Samsung's included) are
        // unreliable at matching filters against UUIDs that land in the scan
        // response rather than the primary advertisement packet.
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        postStatus("Scanning for ESP32-ECG...")
        scanning = true
        scanner.startScan(null, settings, scanCallback)
    }

    fun stop() {
        if (scanning) {
            bluetoothManager.adapter?.bluetoothLeScanner?.stopScan(scanCallback)
            scanning = false
        }
        gatt?.disconnect()
        gatt?.close()
        gatt = null
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val nameMatches = result.device.name == "ESP32-ECG" || result.scanRecord?.deviceName == "ESP32-ECG"
            val uuidMatches = result.scanRecord?.serviceUuids?.contains(ParcelUuid(ECG_SERVICE_UUID)) == true
            if (!nameMatches && !uuidMatches) return

            bluetoothManager.adapter?.bluetoothLeScanner?.stopScan(this)
            scanning = false
            postStatus("Found ${result.device.address}, connecting...")
            gatt = result.device.connectGatt(context, false, gattCallback)
        }

        override fun onScanFailed(errorCode: Int) {
            postStatus("Scan failed: code $errorCode")
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothGatt.STATE_CONNECTED -> {
                    postStatus("Connected, discovering services...")
                    g.discoverServices()
                }
                BluetoothGatt.STATE_DISCONNECTED -> {
                    postStatus("Disconnected")
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val characteristic = g.getService(ECG_SERVICE_UUID)?.getCharacteristic(ECG_CHAR_UUID)
            if (characteristic == null) {
                postStatus("ECG characteristic not found")
                return
            }
            g.setCharacteristicNotification(characteristic, true)
            val cccd = characteristic.getDescriptor(CCCD_UUID)
            if (cccd != null) {
                @Suppress("DEPRECATION")
                cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                @Suppress("DEPRECATION")
                g.writeDescriptor(cccd)
            }
            postStatus("Subscribed to ECG notifications")
        }

        @Suppress("DEPRECATION") // pre-API-33 callback shape; framework still invokes it on newer OS versions too
        override fun onCharacteristicChanged(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val value = characteristic.value ?: return
            parsePacket(value)?.let { postPacket(it) }
        }
    }

    private fun parsePacket(value: ByteArray): EcgPacket? {
        if (value.size < 2) return null
        val seq = value[0].toInt() and 0xFF
        val count = value[1].toInt() and 0xFF
        val samples = IntArray(count)
        for (i in 0 until count) {
            val base = 2 + i * 3
            if (base + 2 >= value.size) break
            var raw = (value[base].toInt() and 0xFF) or
                ((value[base + 1].toInt() and 0xFF) shl 8) or
                ((value[base + 2].toInt() and 0xFF) shl 16)
            if (raw and 0x800000 != 0) raw = raw or -0x1000000 // sign-extend 24-bit -> Int
            samples[i] = raw
        }
        return EcgPacket(seq, count, samples)
    }
}
