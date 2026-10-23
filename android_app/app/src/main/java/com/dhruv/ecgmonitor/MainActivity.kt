package com.dhruv.ecgmonitor

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.safeDrawing
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
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
        // Draw under the status and navigation bars; MonitorContent pads by
        // the insets. Dark style: light icons on the black background.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        setContent {
            val permissionLauncher = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestMultiplePermissions()
            ) { results ->
                if (results.values.all { it }) vm.startBle() else vm.permissionsDenied()
            }

            LaunchedEffect(Unit) {
                // Debug: `adb shell am start -n com.dhruv.ecgmonitor/.MainActivity
                // --es replay dual03_ring` plays a bundled capture instead of BLE.
                val replay = intent.getStringExtra("replay")
                if (replay != null) {
                    vm.startReplay(replay)
                    return@LaunchedEffect
                }
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
    val metrics = LocalContext.current.resources.displayMetrics
    MonitorContent(
        status = vm.status, p = vm.pipeline, tick = vm.packetTick,
        receiving = vm.receiving, gainMmPerMv = vm.gainMmPerMv, onCycleGain = vm::cycleGain,
        xdpi = metrics.xdpi, ydpi = metrics.ydpi,
        insets = WindowInsets.safeDrawing.asPaddingValues(),
    )
}

// Split from MonitorScreen so screenshot tests can render it from a pipeline
// fed by replay, with no ViewModel or BLE, and pass in the phone's DPI and bar
// insets. `tick` must be a parameter: the pipeline is the same instance every
// time, so without a changing argument Compose would skip this function and
// the screen would freeze.
@Composable
internal fun MonitorContent(
    status: String,
    p: EcgPipeline,
    tick: Int,
    receiving: Boolean,
    gainMmPerMv: Int,
    onCycleGain: () -> Unit,
    xdpi: Float,
    ydpi: Float,
    insets: PaddingValues,
) {
    var showFiltered by rememberSaveable { mutableStateOf(true) }
    // Reading the tick (unused otherwise) ties this composable's recomposition
    // to each new packet; everything below re-reads the pipeline fresh.
    @Suppress("UNUSED_EXPRESSION") tick

    MonitorTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize().padding(insets).padding(24.dp)) {
                Text("Status: $status", style = MaterialTheme.typography.bodyLarge)
                Spacer(modifier = Modifier.height(8.dp))
                val lossPct = if (p.packetsSeen + p.packetsLost > 0)
                    100.0 * p.packetsLost / (p.packetsSeen + p.packetsLost) else 0.0
                Text(
                    "seq ${p.lastSeq}  x${p.lastCount}   packets ${p.packetsSeen}   " +
                        "lost ${p.packetsLost} (%.2f%%)".format(lossPct),
                    style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
                )
                Spacer(modifier = Modifier.height(12.dp))

                val sq = p.signalQuality
                // The quality verdict gates the number rather than sitting
                // beside it: a confident wrong heart rate does more damage than
                // an honest refusal to show one. Only GOOD shows a number.
                // Replaying this gate on our recordings (sqi_replay.py) found a
                // chest channel that sat at FAIR 85% of the time while
                // detecting 241 beats against the finger's 186 - FAIR let wrong
                // rates through.
                val trusted = sq.level == SignalQuality.Level.GOOD
                val heartRate = p.heartRate
                Text(
                    if (!trusted || heartRate == null) "— bpm"
                    else "%.0f bpm".format(heartRate),
                    style = TextStyle(
                        fontFamily = PlexSansCondensed, fontWeight = FontWeight.Medium,
                        fontFeatureSettings = TABULAR, fontSize = 44.sp,
                    ),
                    color = if (trusted) MonitorColors.Text else MonitorColors.TextMuted,
                )
                Text(
                    sq.label, style = MaterialTheme.typography.bodyMedium,
                    color = if (trusted) MonitorColors.Text else MonitorColors.TextMuted,
                )
                // RMSSD is unvalidated (root CLAUDE.md status) and stays off this
                // screen until research mode exists to show it, labelled so.
                Text(
                    "kSQI %.1f   pSQI %.2f".format(sq.kSqi, sq.pSqi),
                    style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
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
                    style = MaterialTheme.typography.bodySmall, color = MonitorColors.TextMuted,
                )
                Spacer(modifier = Modifier.height(12.dp))

                EcgTrace(
                    buffer = if (showFiltered) p.sweepFiltered else p.sweepRaw,
                    tick = tick, showTrace = receiving, mmPerMv = gainMmPerMv,
                    xdpi = xdpi, ydpi = ydpi,
                    modifier = Modifier.fillMaxWidth().height(300.dp),
                )
                TraceCaption(gainMmPerMv, onCycleGain)
            }
        }
    }
}
