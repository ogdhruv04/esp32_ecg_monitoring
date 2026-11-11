# Bench session 1

One session at the bench, in this order. It combines `docs/bench_session_plan.md` (clip swap,
calibration-source test, 10-minute dual capture), `android_app/LIVE_TEST.md` (first run of the
phone against the ring) and one check for each of the new sensors. Those two files stay as the
longer explanation of their parts; this is the one to work from on the day.

Each step says what to do, what to look for, and what to save. Write down what you actually
see, including what does not match. A mismatch is a finding, not a failed session. Every figure
quoted later has to come from a file saved here (CLAUDE.md, Rules).

**Nothing in the new firmware has run on hardware.** It compiles for all three boards and the
host tools pass their tests against a simulated stream (`test_capture_sensors.py`). Step 1
exists to find out what that left unproven, before any electrode goes on.

| Step | What | Electrodes | Rough time |
|---|---|---|---|
| 0 | Flash both boards, set up the phone | none | 20 min |
| 1 | Bring-up: boot lines, 1.8 V rail, link test, temperature | none | 15 min |
| 2 | IMU: tap | none | 5 min |
| 3 | Swap the clips: polarity | ECG on both boards | 10 min |
| 4 | PPG: pulse rate against ECG heart rate | ECG + finger on the PPG | 10 min |
| 5 | GSR: circuit test, deep breath, effect on the ECG | GSR, then GSR + ECG | 20 min |
| 6 | Calibration-source test (datasheet check #21, #23) | ECG | 30 min |
| 7 | 10-minute dual capture at rest, phone live | everything | 20 min |
| 8 | Phone: finger lift, reference off, power cycle | ECG on the ring board | 15 min |

The times are guesses. If the session has to be cut, steps 0–3 and 7 are the ones the midterm
needs; 5 and 6 can each move to another day without blocking the others.

## Rules for the whole session

- **Laptop on battery** from before the first electrode touches skin until the last one is off.
  Both boards are powered from its USB and share a ground through it.
- **Three-wire cable at both sites.** Without the third (reference) electrode the finger channel
  went from 0.4% to 43% mains (CLAUDE.md, Status).
- **One label prefix, `b1_`,** on every capture, so the session's files sort together.
- **Run `./integrity.py` on every capture before believing anything from it.** It now checks the
  sensor files as well as the ECG, and prints the firmware's own counters underneath.
- The reference board resets to input configuration `d` (`mode:begin`) on every reboot, and to
  PPG LED current `1F` and a 400 kHz I2C clock.
- Keep one notes file, `captures/<stamp>_b1_notes.txt`, for everything not captured by a tool:
  multimeter readings, times of taps and breaths, what the phone showed.

Bring: a multimeter, a spare 2-pin jumper, two resistors for the GSR test (100 kΩ and 150 kΩ if
you have them; any two between 47 kΩ and 220 kΩ will do), two skin electrodes for the GSR1
header, both 3-wire ECG cables, the phone.

## 0. Before: flash both boards, set up the phone

**Which checkout.** The firmware with the sensors is on the `fw` branch
(`~/esp32_ecg_monitoring-fw`) until merge day, and on `main` after it. Work from whichever has
it, and rebuild there: `build/` and `build_ref/` are per-checkout and not in git.

- [ ] `./build.sh && ./build_ref.sh`. Both `.bin` files (`build/src_build.ino.bin`,
      `build_ref/src_build_ref.ino.bin`) must be newer than `sketch.ino`.
- [ ] **Ring:** attach it to WSL (`usbipd attach --wsl --busid <id>` from PowerShell), then
      `./flash.sh /dev/ttyACM0`. It flashes and opens the monitor.
- [ ] **Reference:** hold BOOT, tap EN, release BOOT; run the `esptool ... write_flash` command
      from CLAUDE.md ("Flashing the reference board"); tap EN. No `chip_id` probe first.
- [ ] **Ring boot lines to look for** (in the monitor that `flash.sh` opens):
  - [ ] `Max30003 read ID Success`
  - [ ] `# sens: none wired on this board`: this line is how you know the new firmware is on it
  - [ ] `# sample rate set to 256 SPS`
  - [ ] `# device: RING  cs=7 int1=10 sync=3 ble=1 sps=256`
  - [ ] `BLE advertising started as ESP32-ECG`
  - [ ] every 5 s a `# 5s:` line with `ovf:0`, `logdrop:0` and `rate` near 256 (it read 256.20
        on 29 Sep, CLAUDE.md Status)
- [ ] Save at least two of those 5 s lines to `captures/<stamp>_b1_boot_ring.log`.

**Phone** (from `android_app/LIVE_TEST.md`; `adb` is `~/Android/Sdk/platform-tools/adb`):

- [ ] Debug APK installed: `cd android_app && ./gradlew assembleDebug`, then
      `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
- [ ] No stale scanner registrations: turn the phone's Bluetooth off and on, then
      `adb shell dumpsys bluetooth_manager | grep -c 'app: com.dhruv.ecgmonitor'` must print 0.
      Leftovers can make the scan fail with `Scan failed: code 2`.
- [ ] One log for the whole session, in its own terminal, left running to the end:
      ```bash
      adb logcat -c
      adb logcat -v time -s EcgMonitor:I BluetoothGatt:D > captures/$(date +%Y%m%d_%H%M%S)_b1_logcat.txt
      ```
- [ ] Screenshots, with `<what>` changed each time:
      `adb exec-out screencap -p > captures/$(date +%Y%m%d_%H%M%S)_b1_<what>.png`

## 1. Bring-up, no electrodes

**1a. Reference boot lines.** These print once at boot, before any capture is running, so
record them on their own. Start the filter below, then tap EN on the reference board:

```bash
./serial_monitor.py /dev/ttyUSB0 460800 | grep --line-buffered -v '^[SPMGTK],' \
  | tee captures/$(date +%Y%m%d_%H%M%S)_b1_boot_ref.log
```

Look for exactly these (`rev:` and `raw:` will be whatever the parts report):

```
# sens: probing, i2c sda=21 scl=22 400000 Hz, gsr adc pin=27
# sens imu: addr:68 whoami:68 smplrt:04 cfg:03 gyro:00 accel:00 pwr:01 every:4 ok
# sens ppg: addr:57 part:15 rev:.. fifo:00 mode:03 spo2:27 pa:1F/1F sps:100 ok
# sens temp: addr:48 cfg:00 raw:.... every:256 ok
# sens gsr: adc pin:27 atten:11dB sum_of:8 every:16 ok
# device: REF  cs=5 int1=15 sync=25 ble=0 sps=256
# cfg emux:0B0000 cal:720000 mode:begin
```

and then, every 5 s, a counter line that should keep `err:0`, `fifo_lost:0` and `logdrop:0`:

```
# sens: i2c:400k ppg:1 n:... fifo_lost:0 err:0 pa:1F part:15 | imu:1@68 n:... err:0 whoami:68 | temp:1 n:... err:0 | gsr:1 n:... | logdrop:0
```

These lines settle open questions 1 and 2 of `docs/sensor_inventory.md`. What a miss means:

| You see | It means | Do |
|---|---|---|
| `no answer at 0x57` / `0x48` / `0x68 or 0x69` | that part is unpowered or absent | check its jumper (HR1 / TEMP1 / GYRO1), tap EN again |
| all three give no answer | the bus itself: wrong pins, or held low | note it and stop the sensor steps; the ECG steps (3, 6, 7, 8) do not depend on it |
| `imu: addr:69` | AD0 is high | fine, the firmware follows it; write it down |
| `whoami` not `68` | not a genuine MPU-6050 | readings continue; note the value, the scale factors are then unverified |
| `part` not `15` | not a MAX30102 | the firmware will not use it |
| `err:` counting up, or `DISABLED after 8 consecutive I2C errors` | marginal bus (see 1b), or a floating AD0 | send `f` to drop the I2C clock to 100 kHz, then `i` to probe again: `printf f > /dev/ttyUSB0; printf i > /dev/ttyUSB0`. If the IMU is the one failing, fit a jumper on AD1 |

**1b. The 1.8 V rail.** With all jumpers on, the I2C pull-ups push current from 3.3 V into the
1.8 V rail (inventory, open question 3). Multimeter, black on ground:

- [ ] 1.8 V rail (either pin of HR1): expect 1.8 V. **If it reads above 2.0 V, pull the HR1
      jumper and stop using the PPG**: 2.0 V is the MAX30102's rated maximum supply and 2.2 V its
      absolute maximum (datasheet check #15), and the MAX30003 is on the same rail.
- [ ] SDA or SCL, idle: the arithmetic says about 2.8 V.
- [ ] Both readings into the notes file. They are the first measurements of this.

**1c. Link test with the sensors streaming.** The firmware now sends roughly twice as much data
from the reference board and uses a larger transmit buffer on both, so the 29 Sep result (both
links clean) has to be earned again. Nothing touching either board:

```bash
./capture_dual.py --seconds 60 --label b1_link
./integrity.py captures/<stamp>_b1_link_ring.csv captures/<stamp>_b1_link_ref.csv
```

Pass, read from `analysis/integrity_<stamp>_b1_link.txt`:

- [ ] ECG, both boards: `missing 0`, `duplicates 0`, `backward jumps 0`. The 29 Sep link test is
      the comparison (`analysis/integrity_20260929_152557_linktest_noelectrodes.txt`).
- [ ] No sensor files for the ring; four for the reference (`_ppg`, `_imu`, `_temp`, `_gsr`).
- [ ] Each sensor file: `missing 0`, `repeated 0`, `backward jumps 0`; `negative 0` on the lag
      line; `skipped readings` 0 or a handful. Note the lag figures: they are the first
      measurement of how long after the ECG interrupt each sensor is actually read.
- [ ] `|accel| median` close to 1 g. This is the accelerometer seeing gravity, the cheapest sign
      that the IMU is real and correctly scaled.
- [ ] The PPG `rate` line: the first measurement of the MAX30102's clock against the ECG clock.
- [ ] Firmware line underneath: `logdrop:0`, `fifo_lost:0`, `err:0`.

If the ECG has gaps here and did not on 29 Sep, the new transmit path is the suspect: stop and
bring the log back. If only sensor rows are missing and `logdrop` is not 0, the firmware is
shedding sensor lines to protect the ECG, as designed, but the buffer needs to be larger.

**1d. Temperature, stable at rest.** No new capture: the link test is 60 s of a board nobody
touched.

```bash
./sensor_check.py captures/<stamp>_b1_link_ref.csv --checks temp
```

- [ ] Provisional pass: sd about the trend at most 0.05 °C and drift at most 0.1 °C/min. A board
      still warming up after power-on will drift; if it fails for that reason, repeat on a later
      capture and say so.
- [ ] Note the level. Room temperature means the sensor reads the board, not skin (inventory,
      open question 8). Then hold a fingertip on U5 for 20 s during any later capture and see
      whether it climbs: that tells us what this sensor can be used for.

## 2. IMU: tap

```bash
./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 40 --label b1_tap
```

- [ ] Hands off for the first 10 s. Then tap the reference board firmly with a fingertip
      **5 times, about 2 s apart**. Hands off for the rest.
- [ ] `./integrity.py captures/<stamp>_b1_tap.csv`, then
      `./sensor_check.py captures/<stamp>_b1_tap.csv --checks imu --taps 5`
- [ ] Pass: `PASS: 5 spikes for 5 taps made`. A spike is at least 50 mg away from the resting
      level and at least 8 robust standard deviations (provisional, top of `sensor_check.py`).
- [ ] If it finds fewer: the readings are 64 per second behind a 44 Hz filter, so a very sharp
      tap can fall between them. Tap harder, or nudge the board, and note which was needed.
      That is information for the motion-artifact work.

## 3. Swap the clips: polarity

From `bench_session_plan.md`, step 1. Electrodes go on now; laptop on battery.

**Arrangement** (the same as dual03, so step 7 repeats it): ring board on the chest, reference
board at the finger. Your call if the bench says otherwise; put the arrangement in the label
as before (`c3chest_wroomfinger`).

- [ ] On **both** 3-wire cables, swap the two non-reference clips. Leave the reference clip.
- [ ] `./capture_dual.py --seconds 60 --label b1_polarity_c3chest_wroomfinger`
- [ ] `./integrity.py` on the pair, then
      `./fiducial.py dual captures/<..>_ring.csv captures/<..>_ref.csv --chest ring`
- [ ] **Answer:** `fiducial.py` prints each channel's whole-recording polarity. It must read
      **+1 on both**; dual03 read −1 on both (`analysis/fiducial_*dual03*_v2.txt`).

Every later capture, and every morphology or amplitude claim, should be in standard polarity.
Detection does not depend on it (tp2 finds the sign itself).

## 4. PPG: pulse rate against ECG heart rate

Reference board only: its own ECG (finger electrodes) and its own PPG, so both are on one clock.

- [ ] Rest a fingertip on the MAX30102 (U8) with light, steady pressure. A finger that presses
      hard or moves gives no pulse.
- [ ] `./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 120 --label b1_ppg`
- [ ] While it runs, from a second terminal, you can step the LED current:
      `printf p > /dev/ttyUSB0`. Each `p` moves to the next of `1F → 3F → 7F → 0A → 1F`
      (6.2, 12.6, 25.4, 2.0 mA typical) and logs `# sens ppg: pa:../.. (set) at ecg_index N`.
      **Only change it if you have to**, and not during the stretch you want to analyse.
- [ ] `./integrity.py captures/<stamp>_b1_ppg.csv`. In the PPG section: `red` and `ir` medians
      well above zero, `at full scale (262143)` equal to 0. Pinned at full scale means too much
      current; a level with no pulse means too little, or pressure.
- [ ] `./sensor_check.py captures/<stamp>_b1_ppg.csv --checks ppg`
- [ ] Pass (provisional): `|difference| <= 2.0 bpm` between the median PPG pulse rate and the
      median ECG heart rate over their common window. At 100 samples per second one sample is
      about 1 bpm at resting rates, so this cannot be tightened much with a plain peak finder.
- [ ] Note the `pulsatile part ... % of the level` figure: it is the first look at perfusion.

This is a liveness check. Pulse arrival time and pulse-rate variability are the Algorithms
stream's work (week 2) and need this recording, so keep it clean.

## 5. GSR

**5a. The circuit, without skin.** One capture, four conditions, 20 s each. Watch the elapsed
time that `capture.py` prints with each `#` line and change at 20, 40 and 60 s; write the
actual times in the notes.

```bash
./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 80 --label b1_gsr_circuit
```

| Seconds | GSR1 header | Prediction from the schematic (`docs/sensor_inventory.md`) |
|---|---|---|
| 0–20 | open | output at its upper limit; this reading *is* the measurement of that limit |
| 20–40 | pins shorted with a jumper | output at its lower limit |
| 40–60 | 100 kΩ across the pins | somewhere in between, set by the trimmer R6 |
| 60–80 | 150 kΩ across the pins | **about 0.47 V above** the 100 kΩ reading, whatever R6 is |

The last line is the test of the transfer function: `V_out = 3 × V_skin − 2 × V_trim` with
`V_skin = 1.65 V × R / (R + 200 kΩ)` gives 0.550 V and 0.707 V at the header for the two
resistors, a difference of 0.157 V, times 3. With other resistor values, use the same formula.
If either resistor reading sits at one of the limits found in the first two rows, turn R6 until
it does not, and repeat.

- [ ] `./integrity.py` on the capture; the GSR section gives the range, and
      `./sensor_check.py captures/<stamp>_b1_gsr_circuit.csv --checks gsr` draws it.
- [ ] Read the four plateau levels off `analysis/sensor_check_<stem>.png` into the notes.
      Agreement with the 0.47 V prediction means the output can later be turned into
      conductance; disagreement means the circuit is not what the schematic says.

**5b. Deep breath.** Two skin electrodes on GSR1, on two fingers of the hand that carries no
ECG electrode. Turn R6 so the output sits clear of both limits, then leave it.

- [ ] `./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 60 --label b1_gsr_breath`
- [ ] Sit still and breathe normally. **At 30 s take one fast, deep breath** and let it out.
      Stay still to the end. Write the real time of the breath in the notes.
- [ ] `./sensor_check.py captures/<stamp>_b1_gsr_breath.csv --checks gsr --breath 30`
- [ ] Pass (provisional): the output moves at least 5 mV, and at least 5 times its robust
      standard deviation in the 10 s before the breath, within 15 s after it.
- [ ] **Expect it to move down.** On this circuit, as drawn, skin conductance rising lowers the
      voltage. So "GSR rises on a deep breath" should appear as a falling trace, typically
      beginning a second or two after the breath. Record the sign you get: it is the first test
      of that reading of the schematic. A response in the other direction is worth as much.
- [ ] No response at all is common with dry or cold hands. Warm them, wait five minutes, try
      once more, and record both attempts.

**5c. Do the GSR electrodes disturb the ECG?** One GSR electrode is the board's ground; the ECG
front end biases the same body through its own third electrode (inventory, open question 6).
With the reference board's ECG electrodes on:

- [ ] `./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 30 --label b1_ecg_gsr_off`,
      GSR electrodes off the skin.
- [ ] The same with `--label b1_ecg_gsr_on`, GSR electrodes on.
- [ ] `./analyze.py` on each, output saved with
      `| tee analysis/analyze_<stamp>_<label>.txt`. Compare the `mains` line and the beat count.
- [ ] **Decide before step 7:** if mains share or beat detection is clearly worse with the GSR
      electrodes on, step 7 runs without them, and GSR gets its own captures until the
      electrodes are isolated. Write the decision and the two figures in the notes.

## 6. Calibration-source test (#21 and #23)

Unchanged from `bench_session_plan.md`, step 2, which has the reasoning and the register
decoding. Commands go to a board as single characters: `printf e > /dev/ttyUSB0` (reference) or
`/dev/ttyACM0` (ring), from a second terminal while a capture is running. Each one echoes the
registers read back from the chip, `# cfg emux:...... cal:...... mode:x (set)`, and the same
line without `(set)` repeats every 5 s, so **check the capture's `.log` before trusting its
label**.

| Command | `CNFG_EMUX` | `CNFG_CAL` | Meaning |
|---|---|---|---|
| `d` | `0B0000` | `720000` | what `begin()` leaves: electrodes connected **and** the calibration sources on both inputs |
| `e` | `000000` | `000000` | electrodes only |
| `c` | `390000` | `702800` | scale test: electrodes disconnected inside the chip, ±0.5 mV square wave at about 16 Hz |

**6a. Does the calibration source load the electrode signal? (#21)** Electrodes on, at rest,
one board at a time: 60 s in `d`, 60 s in `e`, 60 s in `d` again. Labels
`b1_cal_<board>_d1`, `b1_cal_<board>_e`, `b1_cal_<board>_d2`.
*Prediction if it does:* the median R amplitude in `e` is clearly larger than in both `d`
captures. *If not:* the three agree to within the d1–d2 difference.

**6b. Is the code-to-millivolt scale right? (#23)** Configuration `c` on each board, 60 s,
label `b1_cal_<board>_c`. *Prediction from the nominal scale* (1 mV = 2621.44 codes at gain 20;
the formula is from the MAX30001 datasheet, not ours): each edge of the square wave is a
1.0 mV step, about 2,621 codes. The open question is a factor of about ten (dual03 spans
0.136 / 0.153 mV under that scale, `analysis/nominal_mv_scale_dual03.txt`), not a few percent.
The script that measures the step is not written yet; it is part of the Algorithms stream's
week-2 analysis of this session.

- [ ] **Decide the configuration for step 7 now** (`d` or `e`), from 6a, and put it in step 7's
      label. If 6a is not clear on the day, use `d`, which is what dual03 used.

## 7. 10-minute dual capture at rest, phone live

The main recording of the session. It repeats dual03 at six times the length, with the phone
receiving the ring board's stream over BLE at the same time and the reference board's sensors
running.

- [ ] Laptop on battery. Ring board on the chest, reference at the finger (as step 3), seated,
      hands still. Fingertip on the PPG. GSR electrodes on **only if 5c said they are harmless**.
- [ ] Both boards in the configuration chosen in step 6 (send `d` or `e` to each; a board that
      was reset is back in `d`).
- [ ] Phone: open the app, at arm's length from the ring board, not on the desk beside it.
      Look for "Scanning for ring…", then the trace, then "Checking signal", then "Good signal"
      with a number. Serial shows `BLE client connected`, then `BLE notify subscribed`.
      After step 3 the trace should be upright (QRS pointing up); do not flip it in the app. It
      will look small: the app's default gain is 40 mm/mV because the signal measures about
      0.14 mV at the nominal scale (open issue in CLAUDE.md).
- [ ] `./capture_dual.py --seconds 600 --label b1_rest10_<config>_c3chest_wroomfinger`
- [ ] During it: count your pulse for 30 s once and compare it with the phone's number; write
      both down. Take one screenshot of the main screen (`rest10_main`).
- [ ] At the end, before touching anything: Diagnostics on the phone, scrolled to the Packets
      section, screenshot (`rest10_diagnostics`): "Lost" (packets and %), "Samples skipped",
      "Sample rate, last 5 s".

Then, in this order:

```bash
./integrity.py  captures/<..>_ring.csv captures/<..>_ref.csv
./agreement.py  captures/<..>_ring.csv captures/<..>_ref.csv --plot
./fiducial.py dual captures/<..>_ring.csv captures/<..>_ref.csv --chest ring
./sensor_check.py captures/<..>_ref.csv --checks ppg,temp
```

What it answers:

- **Does tp2 hold up on a second, longer recording?** The result rests on one 105 s capture.
- **What is the oscillator drift between the boards?** Over 105 s the estimate's standard error
  was 10.3 ppm (`analysis/agreement_20260929_163314_*_ref.txt`), too large to test anything; it
  falls as T^1.5, so 600 s should bring it under 1 ppm.
- **Is the host-clock rate anomaly real?** 256.04 SPS mid-capture against 255.1 overall on the
  link test (`analysis/integrity_20260929_152557_linktest_noelectrodes.txt`).
- **Phone packet loss and rate, against ground truth.** The ring sends every sample to both
  USB and BLE, so the ring's CSV is what the phone should have received. Provisional target
  from `LIVE_TEST.md`: under 1% packets lost at arm's length. It is a starting point, not
  derived from anything; revise it from this run. In logcat: about 60 `stats` lines with
  `quality=GOOD`, steady `lost=` and `rate=`, and no `link ... -> NOT_CONNECTED`.
- **Ten minutes of PPG, IMU, temperature (and GSR) on the ECG clock**, the first material for
  the week-2 sensor work.

## 8. Phone: finger lift, reference off, power cycle

From `LIVE_TEST.md` items 3–5, which have the full detail. These are about finger contact, so
**move the finger cable to the ring board** for this step (the reference board is not needed).
Logcat is still running. After each, add the cause line exactly as shown, and the `mains=` and
`quality=` values from the nearest `stats` line, to the notes.

- [ ] **Lift the finger** for about 15 s, then press it back. Look for: the number turns into a
      muted "—" within a few seconds; quality drops to "Fair signal" or "Poor signal"; the
      cause line reads "Press your finger fully on the electrode" (or "Hold still" if it only
      drops to Fair); the number returns. Watch for "Check the reference electrode" instead:
      an open electrode can pick up mains, and the cause rule checks mains first. If so, note
      the `mains=` value; it is the first real calibration point for the 10% threshold in
      `MainsMeter.kt`. Screenshot `finger_off`.
- [ ] **Unclip the reference electrode only** for about 20 s, then clip it back. Look for:
      mains share rising a lot in Diagnostics and in `mains=`; if quality leaves GOOD, the
      number becomes "—" and the cause reads "Check the reference electrode". If quality stays
      GOOD the number stays: that is by design (the notch removes mains), so note it, do not
      count it as a failure. Screenshots `ref_off`, `ref_off_diagnostics`.
- [ ] **Unplug the ring's USB** for about 20 s, plug it back, and do not touch the app. Note
      both times. Look for: "Ring not connected" with "Reconnecting…" within about 2 s; after
      power returns the trace and then the number come back by themselves. In logcat, in order:
      `ble status: Disconnected` (or `no data for ... ms on an open link; restarting it` after
      about 8 s), `link RECEIVING -> NOT_CONNECTED`, `reconnecting in 1000 ms` / `2000` / `4000`,
      `Subscribed to ECG notifications`, `stream resumed after N ms; marked M samples as lost`,
      `link NOT_CONNECTED -> RECEIVING`. In Diagnostics: "Lost" did not jump; "Samples skipped"
      rose by about the outage × 256. Watch for `Scan failed: code 6` and `BluetoothGatt`
      `status=133`; either means the reconnect timing needs changing. Screenshots
      `reconnecting`, `reconnected`.

## After the session

- [ ] Stop the logcat terminal (Ctrl+C). Its file holds the whole phone session.
- [ ] Commit `captures/` and `analysis/` from the session, with the notes file.
- [ ] Update CLAUDE.md's status section, quoting only numbers that are in the saved files:
      polarity; the #21 / #23 outcome (and `docs/MAX30003_datasheet_check.md`); drift; phone
      loss and rate; and for the sensors, what the boot lines and the four checks showed.
- [ ] Update `docs/sensor_inventory.md`: strike each open question the session answered, with
      the file that answers it. Revise the provisional pass marks at the top of
      `sensor_check.py` from what was measured.
- [ ] Bring back to the firmware session anything that needed a workaround: `f`, `i`, a pulled
      jumper, sensor rows missing, a skipped-readings count that is not small.
