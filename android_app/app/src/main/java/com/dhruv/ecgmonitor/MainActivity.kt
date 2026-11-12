package com.dhruv.ecgmonitor

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.Surface
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView

class MainActivity : ComponentActivity() {
    private val vm: EcgViewModel by viewModels()

    private val blePermissions = arrayOf(
        Manifest.permission.BLUETOOTH_SCAN,
        Manifest.permission.BLUETOOTH_CONNECT,
        Manifest.permission.ACCESS_FINE_LOCATION
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Draw under the status and navigation bars; the screens pad by the
        // insets. Dark style: light icons on the black background.
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
                // Release builds carry no captures and ignore the extra.
                val replay = intent.getStringExtra("replay")
                if (replay != null && vm.replayAvailable) {
                    vm.startReplay(replay)
                    return@LaunchedEffect
                }
                val granted = blePermissions.all {
                    checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
                }
                if (granted) vm.startBle() else permissionLauncher.launch(blePermissions)
            }

            MonitorApp(vm)
        }
    }
}

// Screens: "main", "diagnostics", "session", "history", or "past:<id>" (a
// stored report opened from History). Saved, so rotation keeps the place.
@Composable
private fun MonitorApp(vm: EcgViewModel) {
    var screen by rememberSaveable { mutableStateOf("main") }
    var trendKey by rememberSaveable { mutableStateOf("rmssd") }
    BackHandler(enabled = screen != "main") {
        screen = when {
            screen.startsWith("past:") -> "history"
            screen == "history" -> "session"
            // Back from a finished report closes it; a recording keeps going.
            screen == "session" && vm.sessionPhase is SessionPhase.Done -> { vm.closeReport(); "main" }
            else -> "main"
        }
    }

    val metrics = LocalContext.current.resources.displayMetrics
    // xdpi/ydpi describe the panel in its natural orientation and Android does
    // not swap them on rotation: in landscape the long axis is horizontal but
    // xdpi still names the short one. Unswapped, 5 mm squares came out 4.973 x
    // 5.029 mm on the test phone (screenshots/after/device_check.txt).
    val rotation = LocalView.current.display?.rotation ?: Surface.ROTATION_0
    val quarterTurn = rotation == Surface.ROTATION_90 || rotation == Surface.ROTATION_270
    val geometry = ScreenGeometry(
        xdpi = if (quarterTurn) metrics.ydpi else metrics.xdpi,
        ydpi = if (quarterTurn) metrics.xdpi else metrics.ydpi,
        insets = WindowInsets.safeDrawing.asPaddingValues(),
    )
    // Screen stays on while data is arriving, and may sleep otherwise.
    val view = LocalView.current
    val receiving = vm.link == Link.RECEIVING
    SideEffect { view.keepScreenOn = receiving }

    val rec = vm.pipeline.session
    val phase = vm.sessionPhase
    val secondsLeft = rec?.let { kotlin.math.ceil((1 - it.progress) * SessionConfig.DURATION_S).toInt() } ?: 0
    val state = MonitorUiState(
        link = vm.link, linkFix = vm.linkFix, dropped = vm.dropped, status = vm.status, replayFile = vm.replayFile,
        pipeline = vm.pipeline, tick = vm.packetTick, gainMmPerMv = vm.gainMmPerMv,
        showFiltered = vm.showFiltered, researchMode = vm.researchMode, sampleRate = vm.sampleRate,
        sessionLabel = when (phase) {
            is SessionPhase.Recording -> "Session %d:%02d".format(secondsLeft / 60, secondsLeft % 60)
            is SessionPhase.Done -> "Session report"
            else -> "Session"
        },
    )
    val actions = MonitorActions(
        onCycleGain = vm::cycleGain,
        onShowFiltered = { vm.showFiltered = it },
        onResearchMode = vm::updateResearchMode,
        onOpenDiagnostics = { screen = "diagnostics" },
        onOpenSession = { screen = "session" },
        onBack = { screen = "main" },
    )
    val sessionActions = SessionActions(
        onStart = vm::startSession,
        onCancel = vm::cancelSession,
        onDone = { vm.closeReport(); screen = "main" },
        onHistory = { if (vm.sessionPhase is SessionPhase.Done) vm.closeReport(); screen = "history" },
        onBack = { screen = "main" },
        onCycleGain = vm::cycleGain,
    )
    val needsHistory = screen == "session" || screen == "history" || screen.startsWith("past:")
    val history by (if (needsHistory) vm.history else kotlinx.coroutines.flow.flowOf(emptyList()))
        .collectAsState(initial = emptyList())
    MonitorTheme {
        Surface(Modifier.fillMaxSize()) {
            when {
                screen == "diagnostics" -> DiagnosticsScreen(state, actions, geometry)
                screen == "session" -> SessionScreen(
                    SessionUiState(
                        phase, state, rec?.progress ?: 0.0, secondsLeft,
                        finishing = rec != null && rec.index >= rec.s1, historyCount = history.size,
                    ),
                    sessionActions, geometry,
                )
                screen == "history" -> HistoryScreen(
                    history, trendKey, { trendKey = it }, { screen = "past:${it.id}" }, { screen = "session" }, geometry.insets,
                )
                screen.startsWith("past:") -> {
                    val r = history.firstOrNull { it.id == screen.removePrefix("past:").toLongOrNull() }
                    if (r != null) ReportScreen(
                        r, geometry.insets, onDone = { screen = "history" }, title = "Past session", doneLabel = "Back",
                        onDelete = { vm.deleteSession(r.id); screen = "history" },
                    )
                }
                else -> MainScreen(state, actions, geometry)
            }
        }
    }
}
