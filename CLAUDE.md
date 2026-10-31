# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ECG acquisition for a finger-electrode ECG ring: ESP32 + MAX30003 firmware, an Android app that filters and detects beats live, and a Python toolchain for capture, analysis and validation. It is a research project. The deliverable is *validated* measurements, so evidence matters more than features. The current plan, with monthly milestones for Sep 2026 – Feb 2027, is `docs/ECG_Ring_SoC_Project_Plan.docx`.

## Two devices, one firmware

`sketch.ino` builds for both boards. The board is selected at compile time by `CONFIG_IDF_TARGET_ESP32C3`:

| | Ring (ESP32-C3 SuperMini) | Reference (ESP32-WROOM-32, custom PCB) |
|---|---|---|
| USB | native USB-CDC → `/dev/ttyACM*` | USB-UART bridge → `/dev/ttyUSB*` |
| CS / INTB / SYNC | GPIO7 / GPIO10 / GPIO3 | IO5 / IO15 / IO25 |
| BLE | on | off |
| Build dir | `build/` | `build_ref/` |

Never fork `sketch.ino` per board. The two-device study only means something because decoding, register config, sample rate and timestamping are byte-identical on both, so the only difference is electrode site. After editing the sketch, **reflash both boards**. To spot a stale device, compare the `.bin` timestamps in `build/` and `build_ref/` against `sketch.ino`.

The reference board's CS is IO5 because an SPI scan read the INFO register as `0x513261` there. The schematic label reads as IO4, which is wrong. That board has no level shifter between the 3.3 V ESP32 and the 1.8 V MAX30003.

## Commands

The build scripts copy `sketch.ino` into `src_build*/` before compiling, so edit `sketch.ino` only.

```bash
./build.sh                 # ring (FQBN esp32:esp32:esp32c3:CDCOnBoot=cdc)
./build_ref.sh             # reference (esp32:esp32:esp32:FlashSize=8M,PartitionScheme=default_8MB)
./flash.sh /dev/ttyACM0    # build + flash ring; pass the port (default is ACM1)
```

In WSL, USB devices must first be attached from Windows with `usbipd attach --wsl --busid <id>`.

**Flashing the reference board.** `flash_ref.sh` does not work unattended, because the board has no auto-reset circuit (its header carries only GND/Vin/RXD0/TXD0). The person at the bench has to do the button steps:
1. Hold BOOT, tap EN, then release BOOT. The board is now in download mode.
2. Run `./build_ref.sh`, then write the image without resetting:
   ```bash
   ~/.arduino15/packages/esp32/tools/esptool_py/5.3.1/esptool --chip esp32 --port /dev/ttyUSB0 \
     --baud 460800 --before no_reset --after no_reset write_flash -z --flash_mode dio \
     --flash_freq 80m --flash_size 8MB \
     0x1000 build_ref/src_build_ref.ino.bootloader.bin \
     0x8000 build_ref/src_build_ref.ino.partitions.bin \
     0xe000 ~/.arduino15/packages/esp32/hardware/esp32/3.3.11/tools/partitions/boot_app0.bin \
     0x10000 build_ref/src_build_ref.ino.bin
   ```
   Do not run a separate `chip_id` probe first; it leaves the stub loaded and the write then fails.
3. Tap EN to run the new firmware. The board stays in download mode until EN is tapped, so repeated writes don't need step 1 again.

**Serial baud.** The C3's native USB ignores the baud rate. On the reference board it is a real UART at `SERIAL_BAUD` (460800), and host tools must match it. `capture.py` and `monitor.sh` default to 57600, so pass `--baud 460800` for the reference board. `serial_monitor.py` asserts DTR, which the C3 needs because its TinyUSB stack withholds output until DTR is set.

```bash
./capture.py --port /dev/ttyUSB0 --baud 460800 --seconds 300 --label rest01   # -> captures/<stamp>_<label>.csv + .log
./capture_dual.py --seconds 300 --label dual01    # ring ACM0 + ref USB0 at once -> <..>_ring/_ref .csv + .log ('#' lines)
./analyze.py captures/<file>.csv [--plot]          # integrity first, then filter/beats/HRV/SQI; mains 50 Hz
./agreement.py captures/<..>_ring.csv captures/<..>_ref.csv [--plot]   # THE correlation result:
                                                   # integrity -> clock offset/drift -> beat Se/P+ -> HR Bland-Altman/ICC/CCC -> RR
./benchmark_mitdb.py --method ours --fs-target 256 [--sqi-gate 0.9] [--check off] [--lead mlii] [--dir D] [--records ..]   # EC57
                                                   # [--positions bp] scores the 5-15 Hz peak instead of tp2
./fiducial.py dual <ring.csv> <ref.csv> --chest ring [--zoom T0 T1]   # timing-point comparison, finger vs chest
./fiducial.py mitdb --dir D --label dev12          # the same against MIT-BIH annotations, with coverage
./integrity.py captures/<..>_ring.csv captures/<..>_ref.csv          # index continuity on the host -> analysis/
cd android_app && ./gradlew assembleDebug          # install with ~/Android/Sdk/platform-tools/adb (wireless debugging)
./make_parity_fixtures.py && (cd android_app && ./gradlew testDebugUnitTest)   # BeatDetector.kt == pan_tompkins.py?
```

`data/` is gitignored, so in a git worktree pass `--dir <main checkout>/data/mitdb` to the benchmark and `fiducial.py`. The benchmark has no single-record option; it always runs every record in `data/mitdb/`. Use `--method neurokit` or `--method pantompkins1985` for comparison detectors. MIT-BIH is US data, so its notch filter is fixed at 60 Hz, while our own recordings use 50 Hz.

## Wireless test board (side task)

A third board, the custom ESP32-C3 in `docs/ESP32C3_custom_schematic.pdf`: a bare C3 with a 40 MHz crystal, an AMS1117-3.3 regulator from VIN, a U.FL antenna connector, and BOOT/EN buttons. It is connected through an FTDI adapter (`/dev/ttyUSB0`, 115200) and has no auto-reset circuit. `wireless_test/wireless_test.ino` tests WiFi and BLE stability on it, and has nothing to do with the ECG signal path.
- `./flash_wtest.sh`: hold BOOT → tap EN → release BOOT first, then run it, then tap EN. It flashes in DIO mode, not QIO.
- WiFi credentials go in `wireless_test/wifi_secrets.h`, which is gitignored; copy it from the `.example.h`.
- `./wireless_test.py --minutes 60 --label soak`: UDP echo (5005) and TCP stream (5006), with the laptop connecting out to the board because of WSL2 NAT. It logs serial and prints PASS/FAIL against the proposed criteria at the top of the script.
- For BLE, it advertises as `C3-WTEST` with the ECG service UUID, so the unmodified phone app connects and shows packet loss.
- Every boot prints `# boot ... reason=... brownouts=N`. BROWNOUT resets under WiFi TX mean VIN is too low for the AMS1117.

## Firmware serial protocol

- `S,index,isr_micros,value,etag,leadoff`: one sample. `value` is the decoded 18-bit signed sample.
- `K,sync_count,sync_micros,sample_index`: a rising edge on SYNC_PIN, for aligning the two devices.
- `# ...`: diagnostics. Every 5 s there is a counter line: `valid ovf empty other rate | life: ... logdrop depth_max isr sweep pin status isr_gap_us`.
- Input: `b` toggles the body-bias drive (RBIAS), `r` resets the FIFO. `d` / `e` / `c` set the input multiplexer and calibration source for the #21/#23 bench test (`d` = what `begin()` leaves, `e` = electrodes only, `c` = internal 1 mV calibration step with the electrodes disconnected; values in `setInputConfig()` and `docs/bench_session_plan.md`).
- `# cfg emux:XXXXXX cal:XXXXXX mode:X`: `CNFG_EMUX` / `CNFG_CAL` **read back from the chip**, at boot (`mode:begin`), on every `d`/`e`/`c` (with `(set)`) and every 5 s, so every capture log records its input configuration. A board resets to `begin` (the `d` values) on every reboot.

**The sample index is the clock.** Sample N was taken at N/256 s, timed by the MAX30003's own 32.768 kHz oscillator. Do timing work on the index, not on host time. Across two devices the oscillators drift by up to ±20 ppm; this figure is from memory and has not been checked against a datasheet. RR intervals are unaffected by a constant offset between devices, but matching individual beats needs the SYNC edges.

## Signal path

MAX30003 FIFO → interrupt-driven drain in firmware → CSV over USB (`capture.py`) or BLE notify (`BleEcgClient.kt`) → the chain below. It spans several files:

- `EcgFilter.kt`: 0.5 Hz high-pass (4th order) → 50/100 Hz notch (Q 30) → 40 Hz low-pass (4th order). This is causal; the delay was measured at 2 samples (7.8 ms). Offline analysis uses zero-phase `filtfilt` instead.
- `BaselineRemover.kt`: 0.6 s rolling median, **display only**. It distorts the ST segment, so never make morphology claims from its output.
- `BeatDetector.kt`: streaming Pan–Tompkins with search-back and threshold stall-decay. **`pan_tompkins.py` is its reference implementation and must stay algorithmically identical.** If you change one, change the other, re-run the benchmark, regenerate the fixtures and run `BeatDetectorParityTest`: it requires the same positions (to 1e-9 samples), the same flags, and the same RMSSD, NN-drop count and coverage on four real-recording cases (chest, finger, artifact + lost packets, polarity inverted mid-recording). **Parameters are frozen in `tp2_config.json`** (version tp2.1): `pan_tompkins.py` reads it, `BeatDetector.kt` hard-codes it and `BeatDetectorConfigTest` fails on any difference. **Beat positions are timing point 2 (tp2, 23 Oct 2026)**: the peak of the dominant QRS deflection, parabolic sub-sample interpolation, located in a detrended window 100 ms before to 60 ms after the 5-15 Hz peak, once that window has fully arrived (up to 60 ms after detection). Polarity comes from the median of the previous 16 beats and is set only when one lobe is 1.5x the other; otherwise, or when the window holds a gap or its maximum sits on the edge, or (tp2.1) when the beat anti-correlates with the median beat at their best alignment within +-39 ms, the beat is **flagged**: its position falls back to the 5-15 Hz peak and it is kept out of HRV. Detection, thresholds and heart rate still run on integrator-peak indices. Python's offline `peaks` keeps warm-up beats, which the phone does not return. `skip(n)` tells both detectors that n samples were lost; the history buffers hold NaN there. HRV uses a 256-deep RR history with one entry per inter-beat interval (NaN when unusable), so `hrvCoverage` is well defined, cleaned before RMSSD (`pan_tompkins.clean_nn` / `rmssd_nn`: 300-2000 ms, drop >20% from the previous accepted interval, seeded from the median of the first 5, re-seeded after 5 consecutive drops, differences only between adjacent accepted intervals). Results from before tp2 are kept and carry no `_tp2` label.
- `SignalQuality.kt`: kSQI (kurtosis) and pSQI (5–15 Hz energy ÷ filtered energy). The GOOD/FAIR thresholds come from published convention and are **not calibrated** on our hardware. bSQI (agreement between two detectors) exists only in the benchmark, not on the phone.

## MAX30003 facts in use

These are checked against the datasheet (`docs/MAX30003 - ... .pdf`, Rev 3). The claim-by-claim record with page numbers is in `docs/MAX30003_datasheet_check.md`. Cite pages from it, and add to it when you rely on a new register detail.

- FIFO word: `[23:6]` 18-bit signed sample, `[5:3]` ETAG, `[2:0]` PTAG (p.41). The ProtoCentral library's `readEcgSample()` gets this wrong (no shift, ETAG ignored), so we decode it ourselves in `readEcgWord()`.
- ETAG (p.42): `0`/`2` valid; `1`/`3` fast-recovery mode, where **time is valid but the voltage is not**; `6` empty; `7` overflow → `FIFO_RST`. EOVF stays asserted until FIFO_RST or SYNCH; a STATUS read doesn't clear it (p.26).
- `EN_INT = 0xC00001` sets EINT + EOVF with the INTB pin in push-pull (p.28). Open-drain (`…03`) left the ring board's interrupt dead; this was measured.
- `MNGR_INT = 0x180004` sets EFIT=3, so the interrupt fires at **4** unread samples (p.29).
- STATUS lead-off bits are `[3:0]`; `0x000200` is the SAMP bit (pp.26–27).
- The library's `begin()` config, decoded: 20 V/V gain, 0.5 Hz on-chip high-pass, 40.96 Hz low-pass at 256 SPS, RBIAS off, and DC lead-off enabled with 0 nA current. Because of that last one, **the `leadoff` column is not a contact indicator** yet.
- **Open issue:** `begin()` routes the internal calibration sources onto both ECG inputs (`CNFG_EMUX = 0x0B0000`, `CNFG_CAL = 0x720000`) with the electrode switches also closed. The datasheet (p.35) recommends opening the input switches in that case. The effect on our signal is untested; see #21 in the check file.

## Rules for this project

- **Every number quoted anywhere** (reports, artifacts, docs, code comments) must come from a saved file in `analysis/` or `captures/`. Re-run the analysis rather than recalling a figure. Figures quoted from memory have drifted before and were published wrong.
- **Judge data integrity from the CSV on the host, not only from the firmware's counters.** Check index continuity and duplicates. The reference capture `20260820_121738_ref_electrodes` lost 0.80% of its samples on the serial link while the firmware reported `logdrop:0`.
- Report Se and P+ separately, together with the rejection rate when a quality gate is used. Never report bare "accuracy".
- **Every HRV result reports its coverage** (share of beats whose interval survives into the NN series) next to the value or the error, per record where there are records. An RMSSD from a few surviving intervals is not the recording's RMSSD.
- **MIT-BIH is split** (`docs/datasets.md`): the 12 records in `data/mitdb` are development data, every parameter was tuned on them; the other 36 are held out. Parameters live in `tp2_config.json` and are not changed in response to held-out results. Every MIT-BIH figure says which set it comes from.
- ECG captured before the FIFO fix (19 Aug 2026) is invalid. Every sample from that period carried the overflow flag.
- When both boards are connected and electrodes are on a person, run the laptop on battery, since the boards share a ground through it.

## Status as of 29 Sep 2026 (update or delete as it changes)

- **FIRST VALID DUAL-SITE RESULT, 29 Sep** (`analysis/agreement_20260929_163314_*`, re-run 30 Sep with default settings): finger vs chest, 105 s at rest, Se 99.44% / P+ 99.44%, HR bias -0.02 bpm (LoA -1.15..+1.12), ICC 0.981, CCC 0.978, RR bias +0.01 ms (LoA +-8.5 ms), RMSSD 36.3 vs 37.3 ms. Month-1 gate (bias < 2 bpm, LoA within +-5 bpm) PASSED. One subject, one posture, hands still - not yet a validation study. Presented in `docs/Finger_vs_Chest_ECG_Results.pptx`; figures in `analysis/slides/` (both tp1). **Re-run with tp2, 23 Oct** (`..._ref_tp2.txt`): Se/P+ unchanged, HR bias +0.03 bpm (LoA -0.10..+0.15), ICC 0.9998, RR LoA +-1.6 ms on 169 intervals (8 flagged out), RMSSD on cleaned NN 18.1 vs 18.0 ms. The slides still show tp1.
- **Electrodes: a reference (third) electrode is essential.** Removing the third clip took the finger channel from 0.4% to 43% mains and killed the QRS band. Both sites need a 3-wire cable; a 2-wire cable gives noise once anything else references the body. Most of 29 Sep went on diagnosing this.
- **Oscillator drift between the boards has NOT been measured.** The earlier "-67 +/- 28 ppm" came from a run with `--skip-s 5`, which leaves settling data in. Sweeping that one flag moves the estimate from -67 to +28 ppm with the sign flipping, because 20 ppm over 105 s accumulates 2.1 ms - less than the 3.0 ms sd of R-peak timing. The fit has no power at this record length. Alignment offset is -16 ms (stable for every `--skip-s` from 10 to 45 s and every `--max-offset` from 1 to 10 s) and is host serial latency, native USB vs FTDI, not physiology. To actually measure drift, wire SYNC between the boards or record for 10 minutes: the slope's standard error falls as T^1.5.
- **There is no hardware sync in use.** `sketch.ino` drives SYNC_PIN and emits `K,` lines, but the pin was never wired between boards, `capture_dual.py` does not parse `K` lines, and every dual capture contains 0 sync markers. All alignment is software, from the beat trains. It works: after alignment, matched beats sit a median 0.2 ms apart with sd 3.0 ms, using 19% of the 150 ms tolerance.
- **Electrode polarity is reversed.** The averaged beat has P, QRS and T all negative at both sites (`analysis/qrs_polarity_dual03.png`); negate it and it is a textbook lead II. The ratio is 4.76:1 negative-to-positive in the raw counts and `readEcgWord()` does no negation, so it is the two non-reference clips being swapped relative to ECGP/ECGN - we are recording lead -II. Detection is polarity-blind (Pan-Tompkins squares the derivative), so no reported number is affected, but every morphology claim is blocked until the clips are swapped and the capture repeated.
- `agreement.py` now writes its settings line into the saved report. A report that omits them cannot be reproduced from itself - that is how the +131 ms figure got published.
- **The app's quality gate, replayed on our recordings** (`sqi_replay.py`, `analysis/sqi_replay_app_gate_dual01-03.txt`): it passes both good dual03 channels 100% GOOD and rejects the failed dual01 run (91-96% POOR). Its weak point is FAIR, which still displays a heart rate: dual02's chest channel sat at FAIR 85% of the time while detecting 241 beats against the finger's 186, so the app would have shown a number from it. The earlier 'pSQI 0.024, marginal' came from `analyze.py`, which computes pSQI differently (whole-recording spectrum, not the app's 5 s time-domain ratio), so it says nothing about the app's thresholds. Three recordings are far too few to calibrate on.
- **Both boards flashed with the current `sketch.ino` on 29 Sep** and verified: ring 256.20 SPS logdrop 0 (was 23,677 on the old build), reference 256.00 SPS ovf 0. They are running identical code.
- **Both links verified clean** by a 3-minute electrode-free dual capture (`captures/20260929_152557_linktest_noelectrodes_*`): 44,548 / 44,545 samples, 0 missing, 0 gaps, 0 duplicates, 0 malformed (`analysis/integrity_20260929_152557_linktest_noelectrodes.txt`). Rate by host clock is 256.04 SPS over the middle 80% but 255.1 SPS over the whole capture on both boards: arrival lag builds to ~0.6 s at the ends with no single stall over 31 ms. The earlier '256.01 SPS' is not reproduced by either method. Cause unresolved; WSL host timing is a suspect. August's 0.80% loss on the reference did not reproduce, and `capture_dual.py` works end to end (boards started 17 ms apart on the host clock).
- **No SPS figure here is an oscillator rate.** Host-measured rates (`capture_dual.py`'s per-board rate; the link test's 255.1 SPS whole-capture and 256.04 SPS mid-capture, `analysis/integrity_20260929_152557_linktest_noelectrodes.txt`) include USB buffering and host timing. The ring's 256.20 and the reference's 256.00 SPS above are not host-measured: they are the firmware's `rate:` field (`sketch.ino`, stats block), samples drained in ~5 s divided by elapsed ESP32 `millis()`, so they reflect where drain batches fall at the window edges and the ESP32's clock. The MAX30003's own rate can only be measured from the sample index against an independent clock: SYNC wiring, or the two boards against each other over a long capture (`docs/bench_session_plan.md`, step 3).
- `agreement.py` was validated on a synthetic pair (same ECG, 500 ms apart, noise and a gap added): it recovered the offset exactly, reported Se 98.3% / P+ 99.4%, HR bias -0.09 bpm, ICC 0.990. It has since been run on three real dual captures.
- **Suspect the WSL/usbip serial path, not the boards.** During the wireless-test side task the kernel logged `vhci_hcd ... urb->status -104`, single serial lines arrived up to 8 times, and opening the port eventually hung. The reference board's 0.80% loss may have the same cause. Worth one capture run from Windows Python on the COM port to compare.
- Wireless test board findings: BLE stable (0 disconnects, 0 notify failures, full rate). WiFi connects only at <=15 dBm TX; at full 19.5 dBm it fails authentication every time. Cause is either supply sag under TX current or the missing U.FL antenna - not yet separated. TCP throughput 0.06-0.12 Mbit/s at -25 dBm is ~100x lower than expected. No antenna is fitted, so no range or soak result is meaningful yet.
- **App, 17 Oct:** stall-decay ported to `BeatDetector.kt` and parity-tested against Python; lost BLE packets now call `detector.skip()`; heart rate shown only on GOOD quality; RMSSD no longer differences two intervals that were not adjacent (a searched-back beat or a gap now breaks the RR series). APK builds; not yet run on the phone with a board.
- **Phone RMSSD, 23 Oct:** now computed from tp2 positions on a cleaned NN series, and pinned to the Python reference by the parity tests (to 1e-9 on all four cases). Validated only offline: finger vs chest on dual03 (one 105 s recording) and against MIT-BIH annotations (`analysis/fiducial_mitdb12_v2.txt`: median RMSSD error -0.02 ms zero-phase / -0.03 ms causal). Not yet run on the phone with the ring, and the finger-vs-chest result needs the second, longer recording in `docs/bench_session_plan.md`. On the two failed recordings (dual01, dual02) tp2 leaves 180 and 106 matched intervals out as flagged and withholds RMSSD, which is the intended behaviour.
- **The phone's RMSSD was about 2x too high, because of lobe-jumping** (`analysis/fiducial_20260929_163314_dual03_both3wire_c3chest_wroomfinger_v2.txt`, causal filter as on the phone, cleaned NN series, all beats). Timing beats from the 5-15 Hz peak (`bp`, tp1), the finger reads **36.7 ms**; from the R peak with parabolic interpolation and the artifact guard (tp2) it reads **17.9 ms**, and the chest agrees (18.0 ms). Under causal filtering the 5-15 Hz peak jumps between QRS lobes on 48 of 179 beats (+-25-39 ms). Under the old HRV rules (no 20% cleaning) the same comparison was 47.0 vs 25.2 ms (`analysis/fiducial_*dual03*.txt`, v1 R+parab). Heart rate was never affected.
- **Fixed 23 Oct: search-back beats were refined to the wrong place** (both detectors searched back from the current sample, up to 1.66 RR after the beat). The fix, not the new timing point, accounts for the whole benchmark gain (`analysis/ec57_benchmark_tp2.txt`, 12-record subset): tp1 Se 98.50 / P+ 97.31 -> 5-15 Hz peak with the fix 99.52 / 98.32 -> tp2 99.50 / 98.30. tp2 is neutral for detection at the 150 ms tolerance; its gain is beat-to-beat timing. With the bSQI 0.9 gate, tp2 gives Se 99.68 / P+ 99.49 at 6.2% rejected (tp1: 99.54 / 99.41 at 11.9%). Ungated P+ still fails the 99% gate, on record 108 (P+ 83.5).
- **Open: a real polarity change takes ~8 beats to follow.** After the sign of the signal flips (the `polarity_flip` fixture inverts it at 30 s), the rolling median still holds the old sign confidently, so those beats are timed on the wrong lobe without being flagged; the 20% cleaning drops 7 intervals but RMSSD still reads 29.9 ms against 18.1 ms for the same finger signal unflipped (`analysis/parity_fixtures_tp2.txt`). On a ring a real flip means the wearer changed finger or orientation. Proposed fix: a per-beat CHECK (not decision) - flag a beat whose window correlates negatively with the median beat - then re-validate.
- **tp2.1 frozen 31 Oct** (commit `da603e2`, `tp2_config.json`): tp2 plus a per-beat correlation check against the median beat at the best alignment within +-39 ms. Unaligned correlation flagged the 48 lobe-jumping beats on dual03 and halved its RMSSD, so alignment is part of the check. Polarity-flip case: mistimed beats 9 -> 0, RMSSD 22.02 vs 22.56 ms unflipped (`analysis/parity_fixtures_tp2.1.txt`). Dev MIT-BIH, causal: worst RMSSD error +16.0 -> -2.5 ms (`analysis/fiducial_mitdb_dev12_v3.txt`).
- **HELD-OUT RESULT, 31 Oct** (36 MIT-BIH records never used in development, run once, frozen parameters; `analysis/heldout_ec57_tp2.1.txt`, `analysis/fiducial_mitdb_heldout32_v3.txt`, `..._heldout_paced4_v3.txt`). Detection, 32 non-paced records, MLII: tp2.1 Se 99.78 / P+ 99.32 ungated; Se 99.82 / P+ 99.89 with the bSQI 0.9 gate at 2.4% rejected (tp2: 99.77 / 99.31; 99.81 / 99.88). Paced (102 104 107 217), separately: 99.55 / 99.24. Record 207 has P+ 80.9; it contains ventricular flutter, which our benchmark scores and EC57 practice may exclude - not changed. HRV: RMSSD error vs annotations, median [range], zero-phase -0.03 [-1.54, +1.94] ms at 72% median coverage; causal (phone) +0.05 [-0.69, +0.91] ms at 60%. R+parab (one polarity per recording) keeps 84-85%.
- **Open, found on held-out: tp2 HRV coverage collapses on biphasic QRS under causal filtering.** 111, 117, 215 and 230 get 0% coverage (RMSSD withheld) on the phone's filter, 112 41%, 118 30%; zero-phase loses less except 118 (1%). Cause (`analysis/heldout_coverage_diagnosis.txt`): entirely the polarity rule - the rolling median beat's lobe ratio is 1.15-1.22 under causal filtering, below POL_RATIO 1.5, so every beat stays undecided and flagged. Accuracy where HRV is reported is good; availability is not. Not retuned: the held-out set is now spent, so any fix needs new held-out data (another database or our own recordings), and dev showed it only on 108.
- **Firmware, 31 Oct:** `d` / `e` / `c` input-configuration commands and the `# cfg` read-back line added to `sketch.ino` on the `analysis` branch; ring and reference images built (`build/`, `build_ref/` in the worktree), **not flashed**. The shared tree has another session's uncommitted `sketch.ino` changes (the `BOARD_TEST_C3` target, in the pin block only), so the two need merging.
- Explainer artifact: https://claude.ai/artifact/8jDzKhFDJhRjZyEzRZhu7S
