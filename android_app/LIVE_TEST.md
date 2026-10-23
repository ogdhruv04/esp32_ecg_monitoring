# First live test: ring board over BLE

A checklist for the first run of the app against the real ring board (ESP32-C3 + MAX30003), not a replay. Work through it in order; each item says what to do, what to look for, and what to save. Everything saved goes in `captures/`, because figures quoted later must come from a saved file (root `CLAUDE.md`, Rules). Write down what you actually see, including what doesn't match the expectation. A mismatch is a finding, not a failed run.

`adb` below is `~/Android/Sdk/platform-tools/adb`. The commands work in fish 3.4+ and bash. Use one label for the whole session; `live01` here.

## Before you start

- [ ] **Laptop on battery.** The ring is powered from the laptop's USB and electrodes go on a person (root `CLAUDE.md`, Rules).
- [ ] **Three-wire cable at the finger.** The reference electrode is essential; without it the finger channel went from 0.4% to 43% mains (root `CLAUDE.md`, Status).
- [ ] **Expect an inverted trace.** The clips are swapped relative to ECGP/ECGN, so we record lead −II and the QRS points down. Don't flip it in the app.
- [ ] **Expect a small trace.** The default gain is 40 mm/mV because the signal measures about 0.14 mV at the nominal scale (open issue in root `CLAUDE.md`).
- [ ] **The debug APK is installed:** `cd android_app && ./gradlew assembleDebug`, then `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
- [ ] **Start one log for the whole session**, in a second terminal, and leave it running until the end:
  ```bash
  adb logcat -c
  adb logcat -v time -s EcgMonitor:I BluetoothGatt:D > captures/$(date +%Y%m%d_%H%M%S)_live01_logcat.txt
  ```
  The app logs under `EcgMonitor`: BLE status messages (`ble status: ...`), link changes (`link SCANNING -> RECEIVING`), reconnect timing (`reconnecting in 1000 ms`), stream breaks (`stream resumed after ... ms`), and every 10 s while data arrives a stats line (`stats packets=... lost=... rate=... quality=... mains=...% headline=...`). `BluetoothGatt` is Android's own connection log, with status codes.
- [ ] **Screenshot command,** with `<what>` changed per item:
  ```bash
  adb exec-out screencap -p > captures/$(date +%Y%m%d_%H%M%S)_live01_<what>.png
  ```

## 1. Flash and check the ring

- [ ] **Attach the ring to WSL** from Windows PowerShell: `usbipd attach --wsl --busid <id>` (`usbipd list` shows the id).
- [ ] **Flash and watch serial:** `./flash.sh /dev/ttyACM0`. It builds, flashes, then opens the serial monitor.
- [ ] **Confirm the build is current:** the `.bin` in `build/` is newer than `sketch.ino`.
- [ ] **Look for, in the serial output:**
  - [ ] `Max30003 read ID Success`
  - [ ] `# sample rate set to 256 SPS`
  - [ ] `# device: ... ble=1 sps=256`
  - [ ] `BLE advertising started as ESP32-ECG`
  - [ ] Every 5 s, a `# 5s: valid:... ovf:0 ... rate:...` line with `ovf:0`, `logdrop:0`, and `rate` near 256. It read 256.20 on 29 Sep (root `CLAUDE.md`, Status).
- [ ] **Save:** copy the serial output (at least two 5 s counter lines) to `captures/<stamp>_live01_flash.log`.

## 2. Connect, good contact: GOOD and a heart rate

- [ ] **Do:**
  1. Open the app.
  2. Place the finger electrodes with the reference clip on and press the finger fully onto the electrode.
  3. Sit still with the hand resting.
- [ ] **Look for, in order:**
  1. "Scanning for ring…" with a small pulsing ring under it.
  2. The trace starts. Serial shows `BLE client connected`, then `BLE notify subscribed`.
  3. "Checking signal" with "Hold still for a few seconds".
  4. "Good signal" with three bars and a number. In the dual03 replay the first number appeared by the 10 s stats line (`screenshots/after/device_logcat_replay.txt`).
- [ ] **Check:** count your pulse for 30 s and compare it with the number shown.
- [ ] **Check:** in logcat, the stats lines say `quality=GOOD` and `headline=Rate(bpm=...)`.
- [ ] **Save:**
  - [ ] a screenshot (`good`)
  - [ ] Diagnostics opened from the "Diagnostics ›" link (`good_diagnostics`)
  - [ ] your pulse count, written in a `captures/<stamp>_live01_notes.txt` that you keep for the session

## 3. Lift the finger: "—" and the right cause line

- [ ] **Do:** lift the finger off the electrode, keep it off for about 15 s, then press it back.
- [ ] **Look for:**
  - [ ] The number turns into a muted "—" within a few seconds, and the quality word drops to "Fair signal" or "Poor signal".
  - [ ] The cause line reads "Press your finger fully on the electrode", or "Hold still" if it only drops to Fair.
  - [ ] Pressing the finger back brings the number back.
- [ ] **Watch for this:** the cause rule checks mains first. An open electrode can pick up mains, in which case the app says "Check the reference electrode" even though the fault is the finger. If that happens, note it with the `mains=` value from the stats lines. That's the first real calibration point for the 10% threshold in `MainsMeter.kt`, which so far rests on three recordings.
- [ ] **Save:**
  - [ ] a screenshot while the finger is off (`finger_off`)
  - [ ] the cause line exactly as shown, and the `mains=` and `quality=` values from the nearest stats line, in the notes

## 4. Remove the reference electrode: the reference-electrode line

- [ ] **Do:** with good contact and a number showing, unclip the reference (third) electrode only. Keep it off for about 20 s, then clip it back.
- [ ] **Look for:**
  - [ ] Mains share rises a lot, both in Diagnostics ("Mains share, raw") and in the `mains=` field of the stats lines.
  - [ ] If quality leaves GOOD, the number becomes "—" and the cause line reads "Check the reference electrode".
- [ ] **Watch for this:** if quality stays GOOD, the number stays. That's by design, because the notch removes mains (the dual02 finger channel was GOOD at up to 66.6% mains, `analysis/mains_share_dual01-03.txt`). Note it rather than treating it as a failure.
- [ ] **Look for:** clipping the reference back brings mains down and the number back.
- [ ] **Save:**
  - [ ] a screenshot of the main screen with the reference off (`ref_off`)
  - [ ] Diagnostics with the reference off (`ref_off_diagnostics`)
  - [ ] the mains and quality values, before, during and after, in the notes

## 5. Ring off and on mid-session: disconnect and reconnect

- [ ] **Do:**
  1. With data flowing, note the time.
  2. Unplug the ring's USB, so the board loses power.
  3. Wait about 20 s.
  4. Plug it back in.

  Nothing else: don't touch the app.
- [ ] **Look for:**
  - [ ] Within about 2 s, "Ring not connected" in red with "Reconnecting…", and the trace stops. The firmware asks for a 1.8 s supervision timeout (`updateConnParams` in `sketch.ino`).
  - [ ] After power returns, the trace and then the number come back by themselves.
- [ ] **Look for, in logcat, in order:**
  1. `ble status: Disconnected`, or, if Android never reports it, `no data for ... ms on an open link; restarting it` after about 8 s.
  2. `link RECEIVING -> NOT_CONNECTED`, then `reconnecting in 1000 ms`, `... 2000 ms`, `... 4000 ms` while the ring is off.
  3. `ble status: Found ..., connecting...`, `Connected, discovering services...`, `Subscribed to ECG notifications`.
  4. `stream resumed after N ms; marked M samples as lost`, then `link NOT_CONNECTED -> RECEIVING`.
- [ ] **Check in Diagnostics:**
  - [ ] "Lost" did not jump (the firmware restarts its sequence numbers on reconnect; that must not count as loss).
  - [ ] "Samples skipped" rose by about the outage length × 256.
- [ ] **Watch for these:**
  - [ ] `Scan failed: code 6`: Android refusing scans that start too often.
  - [ ] `BluetoothGatt` lines with `status=133`: a failed connect.
  - [ ] Either means the reconnect timing needs changing. Note when each appeared.
- [ ] **Save:**
  - [ ] a screenshot while it is reconnecting (`reconnecting`)
  - [ ] a screenshot after it recovers (`reconnected`)
  - [ ] the unplug and replug times in the notes, so the log can be lined up
- [ ] **Optional:** repeat once with a shorter outage of about 3 s.

## 6. Five minutes running: packet loss and sample rate

- [ ] **Do:**
  1. Attach the ring to WSL again if step 5 dropped it.
  2. Start a serial capture alongside the phone: `./capture.py --port /dev/ttyACM0 --seconds 300 --label live01_serial`. The firmware sends every sample to both serial and BLE, so this is the ground truth for what the phone should have received.
  3. Sit still with good contact for the full 5 minutes. The screen should stay on by itself while data arrives.
- [ ] **Look for, in Diagnostics at the end:**
  - [ ] "Lost" (packets and %) and "Samples skipped".
  - [ ] "Sample rate, last 5 s" near the firmware's `rate:` on serial. The phone measures arrival rate by its own clock, so a small difference from 256.20 is expected.
- [ ] **Look for, in logcat:** 30 stats lines, with `lost=` and `rate=` steady and no `link ... -> NOT_CONNECTED`.
- [ ] **Look for, in the capture:** check the CSV with `./analyze.py captures/<stamp>_live01_serial.csv`. It checks integrity first.
- [ ] **There is no agreed pass threshold for packet loss yet.** Record the numbers. The replay gave 0 lost and 256.0 SPS, but a replay has no radio.
- [ ] **Save:**
  - [ ] Diagnostics at the end (`5min_diagnostics`, scrolled to show the Packets section)
  - [ ] the main screen (`5min`)
  - [ ] the capture's `.csv` and `.log`, which `capture.py` writes into `captures/` itself

## Afterwards

- [ ] **Stop the logcat terminal (Ctrl+C).** Its file holds the whole session.
- [ ] **Add the session to the root `CLAUDE.md` status**, quoting only numbers that are in the saved files:
  - [ ] what worked
  - [ ] what didn't
  - [ ] cause lines that came out wrong
  - [ ] the reconnect timing
  - [ ] the 5-minute loss and rate
