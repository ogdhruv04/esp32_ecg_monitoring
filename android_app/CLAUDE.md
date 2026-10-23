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
- Gain: 10 mm/mV by default, 20 and 40 selectable, remembered between launches. The current gain is always printed on the strip next to a 1 mV calibration pulse. The signal is small (see the root CLAUDE.md status), which is why the higher gains exist.
- Polarity: draw the samples as they arrive. The boards currently record lead −II; that's fixed at the electrodes, never by negating in the app.
- The grid is never red; red is for alerts.

## Screens

- Main screen: the trace, heart rate and signal quality. Nothing else.
- Main screen layout, portrait: the heart rate as a large Plex Sans Condensed number with a small "bpm" after it, and the quality word plus a bar glyph under it, all in the top quarter. The trace fills everything below. When the heart rate is hidden, a muted "—" and the cause line sit in the same place, so the layout never jumps.
- Main screen layout, landscape: the trace goes full-bleed, with the heart-rate block in a narrow side column. Never a collapsed strip.
- A small, quiet entry point to Diagnostics, and nothing else on the main screen.
- Diagnostics screen: BLE state, packet loss, sample rate, SQI values (kSQI, pSQI), skip counts, raw/filtered view.
- Heart rate is shown only on GOOD quality. Otherwise show "—" plus one line giving the likely cause and fix: hold still, press the finger fully on the electrode, or check the reference electrode.
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
- `screenshots/before/` is the frozen pre-redesign baseline (its renders are the old app area, 1080 x 2103). `MonitorScreenshotTest` writes to `screenshots/after/`.
- Device screencaps are in Display P3, not sRGB: `#C0392B` captures as (177, 68, 52) (`screenshots/before/device_check.txt`). Convert before comparing colour values.

Design and screenshot work uses replay mode fed from real `captures/` files, never synthetic sine waves. Debug builds bundle `dual03_ring`, `dual03_ref`, `dual02_ring` and `dual01_ring` (mapping in `app/build.gradle.kts`); start one with `adb shell am start -n com.dhruv.ecgmonitor/.MainActivity --es replay dual03_ring`. Replay feeds `EcgPipeline.onPacket` exactly as BLE does, and `ReplayPipelineTest` pins that path to direct detector calls.
