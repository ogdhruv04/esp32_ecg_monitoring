# Android app: UI rules

The app is Compose (Material 3), one activity, `MainActivity.kt`. These rules govern any UI work.

## Hands off the signal path

UI work never changes the logic in `EcgFilter.kt`, `BeatDetector.kt`, `SignalQuality.kt`, `BaselineRemover.kt` or `BleEcgClient.kt`. Read their outputs; don't reimplement or "fix" them from the UI side. `./gradlew testDebugUnitTest` (including `BeatDetectorParityTest`) must pass after every change, not just at the end.

## ECG trace

- A custom Canvas. No chart library.
- Draw ECG paper: 1 mm minor and 5 mm major squares at 25 mm/s and 10 mm/mV. Scale from the screen's physical DPI (`DisplayMetrics.xdpi` / `ydpi`), not from Compose's logical density, which is not millimetres.
- Sweep display: the trace is written left to right at a fixed position and wraps, with an erase bar ahead of the write head. It never scrolls and never autoscales.
- mV conversion: `mV = code × VREF / (2^17 × GAIN)` = code / 2621.44 at VREF 1000 mV, gain 20 V/V. This is `docs/MAX30003_datasheet_check.md` #23 and is **nominal and unverified**. The MAX30003 datasheet doesn't state it. Label the gain as nominal wherever it is shown. If the firmware gain changes, the constant changes with it.
- Gain: 10 mm/mV by default, 20 and 40 selectable, remembered between launches. The current gain is always printed on the strip next to a 1 mV calibration pulse. The signal is small (see the root CLAUDE.md status), which is why the higher gains exist.
- Polarity: draw the samples as they arrive. The boards currently record lead −II; that's fixed at the electrodes, never by negating in the app.
- The grid is never red; red is for alerts.

## Screens

- Main screen: the trace, heart rate and signal quality. Nothing else.
- Diagnostics screen: BLE state, packet loss, sample rate, SQI values (kSQI, pSQI), skip counts, raw/filtered view.
- Heart rate is shown only on GOOD quality. Otherwise show "—" plus one line giving the likely cause and fix: hold still, press the finger fully on the electrode, or check the reference electrode.
- RMSSD is hidden unless research mode is on, and is labelled "unvalidated" there.

## Look

- Dark monitor theme. One accent colour, for the trace. Red is for alerts only.
- Type: IBM Plex Sans and IBM Plex Sans Condensed, bundled in `res/font` (only the weights in use), so Roborazzi renders match the device. No system fonts.
- Tabular digits for every number (`fontFeatureSettings = "tnum"`).
- Never show state by colour alone: pair it with text or a shape.
- No emoji, no gradients.

## Done means rendered

A UI change isn't done until it has been rendered (Roborazzi or `adb exec-out screencap`), the screenshot inspected, and any problems fixed. Check the mm grid on a real device, because a JVM render only knows the DPI it was told.

Design and screenshot work uses replay mode fed from real `captures/` files, never synthetic sine waves. Debug builds bundle `dual03_ring`, `dual03_ref`, `dual02_ring` and `dual01_ring` (mapping in `app/build.gradle.kts`); start one with `adb shell am start -n com.dhruv.ecgmonitor/.MainActivity --es replay dual03_ring`. Replay feeds `EcgPipeline.onPacket` exactly as BLE does, and `ReplayPipelineTest` pins that path to direct detector calls.
