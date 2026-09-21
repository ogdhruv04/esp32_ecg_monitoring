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
./capture_dual.py --seconds 300 --label dual01    # ring ACM0 + ref USB0 at once; not yet validated end to end
./analyze.py captures/<file>.csv [--plot]          # integrity first, then filter/beats/HRV/SQI; mains 50 Hz
./benchmark_mitdb.py --method ours --fs-target 256 [--sqi-gate 0.9]   # EC57 on data/mitdb (12 records)
cd android_app && ./gradlew assembleDebug          # install with ~/Android/Sdk/platform-tools/adb (wireless debugging)
```

The benchmark has no single-record option; it always runs every record in `data/mitdb/`. Use `--method neurokit` or `--method pantompkins1985` for comparison detectors. MIT-BIH is US data, so its notch filter is fixed at 60 Hz, while our own recordings use 50 Hz.

## Firmware serial protocol

- `S,index,isr_micros,value,etag,leadoff`: one sample. `value` is the decoded 18-bit signed sample.
- `K,sync_count,sync_micros,sample_index`: a rising edge on SYNC_PIN, for aligning the two devices.
- `# ...`: diagnostics. Every 5 s there is a counter line: `valid ovf empty other rate | life: ... logdrop depth_max isr sweep pin status isr_gap_us`.
- Input: `b` toggles the body-bias drive (RBIAS), `r` resets the FIFO.

**The sample index is the clock.** Sample N was taken at N/256 s, timed by the MAX30003's own 32.768 kHz oscillator. Do timing work on the index, not on host time. Across two devices the oscillators drift by up to ±20 ppm; this figure is from memory and has not been checked against a datasheet. RR intervals are unaffected by a constant offset between devices, but matching individual beats needs the SYNC edges.

## Signal path

MAX30003 FIFO → interrupt-driven drain in firmware → CSV over USB (`capture.py`) or BLE notify (`BleEcgClient.kt`) → the chain below. It spans several files:

- `EcgFilter.kt`: 0.5 Hz high-pass (4th order) → 50/100 Hz notch (Q 30) → 40 Hz low-pass (4th order). This is causal; the delay was measured at 2 samples (7.8 ms). Offline analysis uses zero-phase `filtfilt` instead.
- `BaselineRemover.kt`: 0.6 s rolling median, **display only**. It distorts the ST segment, so never make morphology claims from its output.
- `BeatDetector.kt`: streaming Pan–Tompkins with search-back and R-peak refinement. **`pan_tompkins.py` is its reference implementation and must stay algorithmically identical.** If you change one, change the other and re-run the benchmark. HRV uses a separate 256-deep RR history (`rrHist`), not the 8-interval threshold window.
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
- ECG captured before the FIFO fix (19 Aug 2026) is invalid. Every sample from that period carried the overflow flag.
- When both boards are connected and electrodes are on a person, run the laptop on battery, since the boards share a ground through it.

## Status as of 21 Sep 2026 (update or delete as it changes)

- Neither board runs the current `sketch.ino` (21 Sep comment fixes; the ring is also on a pre-shared-config build). Reflash both.
- The reference board at 460800 baud has never been verified with a capture.
- No simultaneous chest + finger recording has been made yet, and no agreement-analysis (Bland–Altman/ICC) script exists.
- Explainer artifact: https://claude.ai/artifact/8jDzKhFDJhRjZyEzRZhu7S
