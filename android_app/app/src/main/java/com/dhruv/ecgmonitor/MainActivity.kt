package com.dhruv.ecgmonitor

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    private val vm: EcgViewModel by viewModels()

    private val blePermissions = arrayOf(
        Manifest.permission.BLUETOOTH_SCAN,
        Manifest.permission.BLUETOOTH_CONNECT,
        Manifest.permission.ACCESS_FINE_LOCATION
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val permissionLauncher = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestMultiplePermissions()
            ) { results ->
                if (results.values.all { it }) vm.startBle() else vm.permissionsDenied()
            }

            LaunchedEffect(Unit) {
                val granted = blePermissions.all {
                    checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
                }
                if (granted) vm.startBle() else permissionLauncher.launch(blePermissions)
            }

            MonitorScreen(vm)
        }
    }
}

@Composable
private fun MonitorScreen(vm: EcgViewModel) {
    var showFiltered by rememberSaveable { mutableStateOf(true) }
    // Reading the tick (unused otherwise) ties this composable's recomposition
    // to each new packet; everything below re-reads the pipeline fresh.
    @Suppress("UNUSED_EXPRESSION") vm.packetTick
    val p = vm.pipeline

    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
                Text("Status: ${vm.status}")
                Spacer(modifier = Modifier.height(8.dp))
                val lossPct = if (p.packetsSeen + p.packetsLost > 0)
                    100.0 * p.packetsLost / (p.packetsSeen + p.packetsLost) else 0.0
                Text(
                    "seq ${p.lastSeq}  x${p.lastCount}   packets ${p.packetsSeen}   " +
                        "lost ${p.packetsLost} (%.2f%%)".format(lossPct),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp
                )
                Spacer(modifier = Modifier.height(12.dp))

                val sq = p.signalQuality
                val sqColor = when (sq.level) {
                    SignalQuality.Level.GOOD -> Color(0xFF1E8E3E)
                    SignalQuality.Level.FAIR -> Color(0xFFE37400)
                    SignalQuality.Level.POOR -> Color(0xFFC5221F)
                }
                // The quality verdict gates the number rather than sitting
                // beside it: a confident wrong heart rate does more damage than
                // an honest refusal to show one. Only GOOD shows a number.
                // Replaying this gate on our recordings (sqi_replay.py) found a
                // chest channel that sat at FAIR 85% of the time while
                // detecting 241 beats against the finger's 186 - FAIR let wrong
                // rates through.
                val trusted = sq.level == SignalQuality.Level.GOOD
                val heartRate = p.heartRate
                val rmssd = p.rmssdMs
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
                            "   RMSSD %.0f ms (%d beats)".format(rmssd, p.detector.beatCount)
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
                            "causal (%.1f ms delay)".format(p.filter.groupDelayMs)
                    else "raw ADC codes, unfiltered",
                    fontSize = 11.sp,
                    color = Color(0xFF666666)
                )
                Spacer(modifier = Modifier.height(12.dp))

                EcgChart(
                    samples = if (showFiltered) p.filteredBuffer.snapshot() else p.rawBuffer.snapshot(),
                    color = if (showFiltered) Color(0xFFC0392B) else Color(0xFF888888),
                    modifier = Modifier.fillMaxWidth().height(300.dp)
                )
            }
        }
    }
}
