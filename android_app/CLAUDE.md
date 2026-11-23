# Android app: UI rules

The app is Compose (Material 3), one activity, `MainActivity.kt`. These rules govern any UI work.

## Hands off the signal path

UI work never changes the logic in `EcgFilter.kt`, `BeatDetector.kt`, `SignalQuality.kt`, `BaselineRemover.kt` or `BleEcgClient.kt`. Read their outputs; don't reimplement or "fix" them from the UI side. `./gradlew testDebugUnitTest` (including `BeatDetectorParityTest`) must pass after every change, not just at the end.

## ECG trace

- A custom Canvas. No chart library.
- Draw ECG paper: 1 mm minor and 5 mm major squares at 25 mm/s and 10 mm/mV. Scale from the screen's physical DPI (`DisplayMetrics.xdpi` / `ydpi`), not from Compose's logical density, which is not millimetres.
- Sweep display: the trace is written left to right at a fixed position and wraps, with an erase gap (0.2 s) ahead of the write head. It never scrolls and never autoscales. Lost packets are gaps in the line, never joined across (`SweepBuffer` keeps them as NaN; `SweepTest` pins the rules). With no packets for 1 s, only the grid shows.
- Stroke 1.5 dp, round joins, no glow or shadow. The 1 mV calibration pulse sits at the left edge, and 0 mV moves down a major line when needed so the whole pulse stays on screen at 40 mm/mV.
- Grid scale on the test phone was measured from a screencap and checked with a ruler (pulse 10 x 5 mm): `screenshots/after/device_check.txt`.
- mV conversion: `mV = code × VREF / (2^17 × GAIN)` = code / 2621.44 at VREF 1000 mV, gain 20 V/V. This is `docs/MAX30003_datasheet_check.md` #23 and is **nominal and unverified**. The MAX30003 datasheet doesn't state it. Label the gain as nominal wherever it is shown. If the firmware gain changes, the constant changes with it.
- Gain: 10, 20 and 40 mm/mV, cycled by tapping the gain label, remembered between launches. **The default is 40 for now**, because at 10 our 0.14 mV signal looks flat. When the root CLAUDE.md amplitude issue is resolved, set `DEFAULT_GAIN_MM_PER_MV` back to 10; a user's saved choice is kept either way. The current gain is always printed on the strip next to a 1 mV calibration pulse.
- The calibration pulse is drawn in the muted text colour, to scale. 0 mV sits on the major line nearest the middle, or lower when that is what it takes to keep the whole pulse on screen.
- The strip runs edge to edge with no border and takes all the height left over; partial squares at its edges are fine.
- DPI per axis: `DisplayMetrics.xdpi/ydpi` describe the panel's natural axes and Android does not swap them on rotation. `MainActivity` swaps them at 90/270 degrees; unswapped, landscape squares were 4.973 x 5.029 mm (`screenshots/after/device_check.txt`).
- Polarity: draw the samples as they arrive. The boards currently record lead −II; that's fixed at the electrodes, never by negating in the app.
- The grid is never red; red is for alerts.

## Screens

- Main screen: the trace, heart rate and signal quality. Nothing else, apart from the two entry points below.
- Main screen layout, portrait: the heart rate as a large Plex Sans Condensed number with a small "bpm" after it, and the quality word plus a bar glyph under it, all in the top quarter. The trace fills everything below. When the heart rate is hidden, a muted "—" and the cause line sit in the same place, so the layout never jumps.
- Main screen layout, landscape: the trace goes full-bleed, with the heart-rate block in a narrow side column. Never a collapsed strip.
- Two small, quiet entry points, "Session ›" and "Diagnostics ›", after the trace caption; nothing else on the main screen. While a session records, the Session link shows the time left. The caption and links share a `FlowRow`, so at a large font the links wrap whole onto their own line instead of squeezing the caption.
- Diagnostics screen: BLE state, packet loss, sample rate, SQI values (kSQI, pSQI), skip counts, raw/filtered view.
- The heart rate on every screen is `EcgPipeline.heartRate` from `LiveHeartRate.kt` (located beats, last 10 s, plausibility and agreement tests), never `BeatDetector.heartRate`: that 8-interval window sets the search-back threshold and showed 27 and 101 bpm on a GOOD tb02 replay (`analysis/app_live_hr.txt`). `LiveHeartRateTest` pins it against an independent reference on tb02 and dual03. When it gives no rate on GOOD, the headline says "Measuring".
- Heart rate is shown only on GOOD quality. Otherwise show "—" plus one line giving the likely cause and fix: hold still, press the finger fully on the electrode, or check the reference electrode. The rules live in `headline()` (`MonitorUi.kt`, pinned by `HeadlineTest`). "Check the reference electrode" fires when quality isn't GOOD and mains is at least 10% of raw power, a threshold from three recordings of one subject (`analysis/mains_share_dual01-03.txt`), so uncalibrated.
- With no packets the heart-rate area reads "Scanning for ring…" (with a quiet animated ping) or "Ring not connected", never a zero or -1. "Ring not connected" is red only after a live stream dropped this session; before the first connection it is plain text. In debug builds a replay shows a permanent "REPLAY · <file>" tag.
- The screen is kept on only while packets are arriving (`View.keepScreenOn`).

## Session mode

`docs/explained/app.md` explains the measurement side; these are the rules.

- Two kinds (`SessionKind`, `session_config.json`): standard 3 min, extended 5 min. Only the extended report has DFA α1 and sample entropy; a 3-minute session cannot meet their minimums. Start waits until the main screen would show a heart rate (GOOD). Back leaves the screen and recording continues; Cancel stops it.
- Every measure is a port of `algorithms/` (`app/src/main/java/.../algorithms/`), never reimplemented from the UI. If the Python changes: `./make_session_fixtures.py`, then `HrvParityTest`, `SessionParityTest` and `AlgorithmsConfigTest` must pass.
- Session-level rules (HR intervals, breathing windows and their spread) come from `algorithms/config.json`. It has no `session` block yet, so `SessionRules` holds provisional values and every reason they produce says "(provisional rule)". `AlgorithmsConfigTest` fails when the block appears; take the values from it then.
- The report has two layers: a summary of HR, RMSSD and breathing rate, each with "Usual" (median and range) once there are `BASELINE_MIN_SESSIONS` (3) earlier live sessions, or "Building your baseline: N of 3" before that; and "All measures", collapsed. Replays never count towards the baseline (`Baseline.kt`, `BaselineTest`).
- Tapping a measure shows one line from `EXPLANATIONS`. That wording is reviewed in `docs/explained/app.md`; `ExplanationsTest` requires the two to match, so change both together.
- A withheld measure shows "—" and the algorithm's reason verbatim. Every shown HRV value carries its count and coverage. LF/HF always carries the band-ratio caveat.
- Rhythm check, ectopic count, motion and arousal are stored slots (`PendingSlots`) and are not drawn (`PENDING_SLOTS_VISIBLE`) until a validated algorithm fills them.
- Reports are saved to Room (`SessionStore.kt`, schema 2; schemas in `app/schemas/`, also served to debug assets for `SessionMigrationTest`). A schema change needs a migration and a migration test.
- History plots one unjoined point per session at its date: dots live, squares replay, a tick under the axis for withheld, a dashed median; first and last dates always labelled.
- `EcgPipeline` feeds the recorder in a fixed order (sample, then detector, then end check; skips with the detector). `SessionParityTest` and `SessionPipelineTest` pin that order. Don't reorder it.

## Guided breathing

- `GuidedBreathingUi.kt`, from the Session screen. Pacer 6/min, 5 s in, 5 s out, 3 min (`GuidedBreathingConfig`, `session_config.json`), drawn by the frame clock while running. The phase text sits under the circle, never on it.
- Live numbers come only from `LiveHrv` (sliding windows over `EcgPipeline.live`): RMSSD of the last 90 s and fused breathing of the last 32 s under their usual minimums, and the beat-to-beat heart-rate curve of accepted NN intervals with the in-breaths shaded. `LiveHrvParityTest` pins them to `session_reference.live_window`.
- Heart rate on this screen follows the main screen's rule (GOOD only). Nothing from the exercise is stored.

## BLE link

- `BleEcgClient` never reconnects: on a drop it posts "Disconnected" and leaves its GATT open. `EcgViewModel` closes it and starts a fresh client after 1, 2, 4, 8, 16, then 30 s, resetting once data flows; it also restarts a link that goes 8 s without data and without a disconnect. `ReconnectTest` covers it (on SDK 33, so it has its own Robolectric sandbox: sharing one with the Compose tests made the clock jump mid-test).
- `BleEcgClient` releases its GATT (`close()`) on disconnect and on a missing ECG characteristic: `disconnect()` alone leaves the client registered with the stack, one more per reconnect. `BleConnectionReleaseTest` pins it on the real client through Robolectric's Bluetooth shadows (`SimulatedRing`), and `ReconnectTest` runs ten real reconnect cycles and requires no GATT left open.
- Android keeps an app's LE scanner registrations from processes that were killed without stopping their scan (seen on the test phone, `screenshots/after/device_check.txt`). Toggle Bluetooth before a live session (`LIVE_TEST.md`).
- The firmware restarts seq at 0 on each subscribe, so a reconnection calls `EcgPipeline.breakStream()` with the outage length by wall clock: the trace shows a gap and the RR across it is dropped, instead of counting bogus lost packets.
- Log tag `EcgMonitor`: BLE status messages, link transitions, reconnect timing, stream breaks, and a stats line every 10 s while receiving. `adb logcat -s EcgMonitor:I` is the record of a live session.
- RMSSD is hidden unless research mode is on, and is labelled "unvalidated" there.

## Look

- Dark monitor theme. One accent colour, for the trace. Red is for alerts only.
- Type: IBM Plex Sans and IBM Plex Sans Condensed, bundled in `res/font` (only the weights in use), so Roborazzi renders match the device. No system fonts.
- Tabular digits for every number (`fontFeatureSettings = "tnum"`). Plex's default figures are already tabular and the fonts have no `tnum` feature (`third_party/ibm-plex/README.md`), so the setting is a guard for a future font change, not what makes it work.
- Never show state by colour alone: pair it with text or a shape.
- No emoji, no gradients.

## Done means rendered

A UI change isn't done until it has been rendered (Roborazzi or `adb exec-out screencap`), the screenshot inspected, and any problems fixed. Check the mm grid on a real device, because a JVM render only knows the DPI it was told.

- **Roborazzi** runs inside `./gradlew testDebugUnitTest` (record mode is always on; Robolectric native graphics). `MonitorScreenshotTest` renders the screen from replay at 20 s and asserts the quality state each image is meant to show. Renders are byte-identical run to run.
- Device config is the test phone, a Galaxy A56 (SM-A566E): 1080 x 2340 px, logical density 450, physical DPI 386.37 x 388.47 (`screenshots/before/device_check.txt`). The app is edge-to-edge, so a render is the whole screen; the test passes the phone's bar insets (status 101 px, nav 135 px) and physical DPI in, so a render lines up with a screencap.
- Text scales with the system font. Heart-rate block slots are sized from what they can hold: the cause and message slots measure their longest possible text at the current width and font (`CAUSE_TEXTS`, `MESSAGE_TEXTS` in `MonitorUi.kt`; add any new message there), so nothing clips at 1.3x or 2x and the block still never changes size within a session. Don't size text slots by converting sp to dp by hand: at large scales the layout's line height and `TextUnit.toDp()` disagree by a few pixels, which dropped a line. `MonitorScreenshots` renders the main screen at font scale 1.3 and 2.0 (`*_font130_*`, `*_font200_*`).
- Release builds bundle no captures and ignore the `replay` extra; for on-phone checks they are signed with the debug key (`app/build.gradle.kts`). A build for anyone else needs a real release key.
- `screenshots/before/` is the frozen pre-redesign baseline (its renders are the old app area, 1080 x 2103). `MonitorScreenshots` (portrait and landscape subclasses) writes every main-screen state and Diagnostics to `screenshots/after/<state>_<orientation>.png`, Diagnostics also scrolled to its end.
- A render is a first composition, so it can't show a part of the screen that stops updating. Never pass the pipeline itself to a small composable: it is the same instance every frame and Compose will skip it. Pass values. `MonitorRecompositionTest` drives one composition through a live stream.
- Device screencaps are in Display P3, not sRGB: `#C0392B` captures as (177, 68, 52) (`screenshots/before/device_check.txt`). Convert before comparing colour values.

Design and screenshot work uses replay mode fed from real `captures/` files, never synthetic sine waves. Debug builds bundle `dual03_ring`, `dual03_ref`, `dual02_ring`, `dual01_ring`, and the test-board captures `tb01` and `tb02`, the only ones longer than a session (mapping in `app/build.gradle.kts`). `./make_public_replay.py --dir <main checkout>/data/mitdb` adds MIT-BIH development record 103 as `mitdb103` from the gitignored `replay_public/`: the only replay on which the whole Session report fills. It is never committed, and its screenshot tests skip without it; start one with `adb shell am start -n com.dhruv.ecgmonitor/.MainActivity --es replay dual03_ring`. Replay feeds `EcgPipeline.onPacket` exactly as BLE does, and `ReplayPipelineTest` pins that path to direct detector calls.
