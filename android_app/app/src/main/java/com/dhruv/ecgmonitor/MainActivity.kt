package com.dhruv.ecgmonitor

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    private var bleClient: BleEcgClient? = null

    // Two views of the same stream. Raw is what the sensor sends; filtered is
    // what is actually readable. Kept side by side because the difference is
    // the whole point - ~97% of raw power on our bench sits at 50 Hz mains.
    private val rawBuffer = EcgRingBuffer()
    private val filteredBuffer = EcgRingBuffer()
    private val filter = EcgFilter()
    private val baseline = BaselineRemover()
    private val detector = BeatDetector()
    private val quality = SignalQuality()
    // Bandpassed 5-15 Hz copy, kept only to feed the pSQI energy ratio.
    private val qrsBuffer = EcgRingBuffer()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            var status by remember { mutableStateOf("Waiting for Bluetooth permissions...") }
            var lastSeq by remember { mutableIntStateOf(-1) }
            var lastCount by remember { mutableIntStateOf(0) }
            var packetsSeen by remember { mutableIntStateOf(0) }
            var packetsLost by remember { mutableIntStateOf(0) }
            var showFiltered by remember { mutableStateOf(true) }
            var heartRate by remember { mutableStateOf<Double?>(null) }
            var rmssd by remember { mutableStateOf<Double?>(null) }
            // Bumped on every packet purely to trigger recomposition of the
            // chart - the ring buffer itself is plain (non-Compose-observed)
            // state read fresh from it each time this changes.
            var tick by remember { mutableIntStateOf(0) }

            val permissionLauncher = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestMultiplePermissions()
            ) { results ->
                if (results.values.all { it }) {
                    status = "Permissions granted, starting scan..."
                    val client = BleEcgClient(this, object : BleEcgListener {
                        override fun onStatus(s: String) { status = s }
                        override fun onPacket(packet: EcgPacket) {
                            // seq is a byte that wraps at 256. A gap means the
                            // notification never arrived, which is 6 missing
                            // samples and one corrupted RR interval - so it has
                            // to be counted, not just tolerated. The detector is
                            // told too, so it keeps time across the hole and
                            // drops the RR interval that spans it. Lost packets
                            // are assumed to have carried as many samples as
                            // the last one that arrived.
                            if (lastSeq >= 0) {
                                val gap = (packet.seq - lastSeq + 256) % 256 - 1
                                if (gap > 0) {
                                    packetsLost += gap
                                    detector.skip(gap * lastCount)
                                }
                            }
                            lastSeq = packet.seq
                            lastCount = packet.count
                            packetsSeen++
                            for (v in packet.samples) {
                                rawBuffer.push(v.toFloat())
                                // Detector runs on the filter output, matching
                                // what the MIT-BIH benchmark was run against.
                                // Baseline removal is display-only and must not
                                // sit between them, or the validation numbers
                                // stop applying to what is on screen.
                                val f = filter.process(v)
                                detector.process(f)
                                filteredBuffer.push(baseline.process(f))
                                qrsBuffer.push(detector.lastBandpassed)
                            }
                            heartRate = detector.heartRate
                            rmssd = detector.rmssdMs
                            tick++
                        }
                    })
                    bleClient = client
                    client.start()
                } else {
                    status = "Bluetooth permissions denied - cannot scan/connect"
                }
            }

            LaunchedEffect(Unit) {
                permissionLauncher.launch(
                    arrayOf(
                        Manifest.permission.BLUETOOTH_SCAN,
                        Manifest.permission.BLUETOOTH_CONNECT,
                        Manifest.permission.ACCESS_FINE_LOCATION
                    )
                )
            }

            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
                        Text("Status: $status")
                        Spacer(modifier = Modifier.height(8.dp))
                        val lossPct = if (packetsSeen + packetsLost > 0)
                            100.0 * packetsLost / (packetsSeen + packetsLost) else 0.0
                        Text(
                            "seq $lastSeq  x$lastCount   packets $packetsSeen   " +
                                "lost $packetsLost (%.2f%%)".format(lossPct),
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp
                        )
                        Spacer(modifier = Modifier.height(12.dp))

                        val snap = filteredBuffer.snapshot()
                        val sq = quality.assess(snap, qrsBuffer.snapshot())
                        val sqColor = when (sq.level) {
                            SignalQuality.Level.GOOD -> Color(0xFF1E8E3E)
                            SignalQuality.Level.FAIR -> Color(0xFFE37400)
                            SignalQuality.Level.POOR -> Color(0xFFC5221F)
                        }
                        // The quality verdict gates the number rather than
                        // sitting beside it: a confident wrong heart rate does
                        // more damage than an honest refusal to show one.
                        // Only GOOD shows a number. Replaying this gate on our
                        // recordings (sqi_replay.py) found a chest channel that
                        // sat at FAIR 85% of the time while detecting 241 beats
                        // against the finger's 186 - FAIR let wrong rates through.
                        val trusted = sq.level == SignalQuality.Level.GOOD
                        Text(
                            if (!trusted || heartRate == null) "-- bpm"
                            else "%.0f bpm".format(heartRate),
                            fontSize = 44.sp,
                            color = if (trusted) Color(0xFF202124) else Color(0xFFAAAAAA)
                        )
                        Text(sq.label, fontSize = 13.sp, color = sqColor)
                        Text(
                            "kSQI %.1f   pSQI %.2f%s".format(
                                sq.kSqi, sq.pSqi,
                                if (rmssd != null && sq.level == SignalQuality.Level.GOOD)
                                    "   RMSSD %.0f ms (%d beats)".format(rmssd, detector.beatCount)
                                else "   RMSSD: needs %d beats".format(BeatDetector.MIN_BEATS_FOR_HRV)
                            ),
                            fontFamily = FontFamily.Monospace, fontSize = 11.sp,
                            color = Color(0xFF888888)
                        )
                        Spacer(modifier = Modifier.height(12.dp))

                        Row {
                            FilterChip(
                                selected = showFiltered,
                                onClick = { showFiltered = true },
                                label = { Text("Filtered") }
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            FilterChip(
                                selected = !showFiltered,
                                onClick = { showFiltered = false },
                                label = { Text("Raw") }
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            if (showFiltered)
                                "0.5Hz HP4 -> 50/100Hz notch -> 40Hz LP -> median detrend, " +
                                    "causal (%.1f ms delay)".format(filter.groupDelayMs)
                            else "raw ADC codes, unfiltered",
                            fontSize = 11.sp,
                            color = Color(0xFF666666)
                        )
                        Spacer(modifier = Modifier.height(12.dp))

                        // Reading tick here (unused otherwise) ties this
                        // composable's recomposition to each new packet.
                        @Suppress("UNUSED_EXPRESSION") tick
                        EcgChart(
                            samples = if (showFiltered) snap else rawBuffer.snapshot(),
                            color = if (showFiltered) Color(0xFFC0392B) else Color(0xFF888888),
                            modifier = Modifier.fillMaxWidth().height(300.dp)
                        )
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        bleClient?.stop()
    }
}
