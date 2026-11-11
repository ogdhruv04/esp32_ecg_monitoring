# Midterm plan: 10 Nov – 7 Dec 2026

Every Claude Code session reads this file first and ticks off its own items at the end.
Each workstream edits **only its own section**, so the branches merge cleanly on merge day.

**Midterm story:** validated acquisition → validated beat timing (held-out MIT-BIH) →
finger-vs-chest agreement → a multi-sensor "autonomic session" on the reference hardware:
HRV, breathing rate, rhythm check, ectopic beats, motion-aware quality and an arousal index
against the wearer's own baseline. Each one is validated, and each one is shown in the app.

**Rules for every workstream**
- Every number traces to a saved file in `analysis/` (existing CLAUDE.md rule).
- Freeze parameters before any held-out test. Split by patient/subject, never by beat.
- Report coverage or rejection rate next to every accuracy figure. Never report bare "accuracy".
- Deep learning only if it beats the classical baseline on the same held-out split.
- Arousal, not "stress": no psychological claims.
- Not in scope: MI/ischaemia, hyperkalemia, cuffless BP, glucose, clinical SpO2.

**Merge day:** every Sunday the consolidation session merges all workstream branches into
`main`, runs every test, and pushes.

---

## Week 1 (10–16 Nov): foundations

### Consolidation
- [x] Merge `ui-redesign` into `main`, then merge `analysis` (combine BOARD_TEST_C3 pins with the calibration commands)
- [x] All Python and Android tests pass on `main`; pushed; analysis worktree removed
- [x] This file committed; CLAUDE.md says every session reads it

### Firmware (`fw` branch)
- [ ] Sensor inventory: board, bus and pins for MAX30102 (PPG), MAX30205 (temperature), MPU6050 (IMU) and GSR (IO27); list the unknowns
- [ ] Sensors in the firmware stream, timestamped against the ECG sample index
- [ ] `capture.py` / `capture_dual.py` save the new streams; integrity check covers them
- [ ] `docs/bench_session_1.md` written; both images built, not flashed

### Algorithms (`algo` branch)
- [x] `algorithms/` package: HRV time-domain, Lomb–Scargle LF/HF, Poincaré SD1/SD2, DFA α1, sample entropy, each with an enforced minimum window (`docs/hrv_minimum_windows.md`; 50 unit tests in `tests/`)
- [x] HRV functions checked against neurokit2 on MIT-BIH (`analysis/hrv_vs_neurokit_mitdb_dev.txt`, `..._heldout.txt`)
- [x] ECG-derived breathing rate (RSA and R-amplitude) validated on BIDMC against annotated breaths (`analysis/breathing_bidmc_dev.txt`, `..._heldout.txt`; split by subject, parameters frozen in commit `467881d` before the held-out run)
- Found on the way, for the app plan: a 2-minute session cannot hold the 120 s of valid NN time that SDNN, SD2, LF/HF and DFA α1 need (`docs/hrv_minimum_windows.md`, last section). Session length is a decision for week 3.

### You
- [ ] Answer: sensor wiring, midterm date, whether Phase 2 (SoC) is assessed, ethics status
- [ ] Send the current State of the Art section or report template to the review chat
- [ ] **Bench session 1** (end of week): flash both boards, swap clips, calibration test, 10-min dual capture with the phone live, one check per sensor

## Week 2 (17–23 Nov): rhythm, sensors, motion

### Algorithms
- [ ] Bench session 1 analysed: amplitude (calibration test), 10-min HRV finger vs chest, oscillator drift, upright polarity
- [ ] Ectopic beats: template correlation plus prematurity, MIT-BIH inter-patient split (de Chazal DS1/DS2), Se/P+ for V beats
- [ ] AF screening: RR-irregularity features plus a classical model on CinC 2017, patient-wise split, frozen and then held-out; F1 per class
- [ ] Motion-artifact detection from the IMU, feeding the quality gate, evaluated on the protocol's motion segment
- [ ] PPG: beat detection, pulse-rate variability vs ECG HRV (agreement), pulse arrival time, perfusion index; SpO2 only as an uncalibrated ratio
- [ ] GSR: tonic/phasic decomposition, skin-response count; temperature slope

### Firmware
- [ ] Fixes from bench session 1; the new sensor streams over BLE, if they're on the BLE board

### You
- [ ] **Bench session 2** on 3 different days, all sensors: rest 3 min → paced breathing at 6/min for 3 min → mental arithmetic 3 min → light hand motion 2 min → recovery 3 min

## Week 3 (24–30 Nov): into the app

### App (`app` branch)
- [ ] "Session" mode: 2-min recording → report (HR, HRV, breathing rate, rhythm check, ectopic count, quality and motion, arousal vs baseline)
- [ ] Guided-breathing screen with live HRV (breathing at 6/min)
- [ ] Session history stored on the phone (Room), with trends against a personal baseline
- [ ] Every ported algorithm has a parity test against its Python reference

### Algorithms
- [ ] Arousal index: HRV, GSR, temperature and PPG features z-scored against the wearer's baseline; leave-one-day-out evaluation on the protocol data; per-feature ablation

### You
- [ ] State of the Art rewrite, drafted with the review chat

## Week 4 (1–7 Dec): evaluation and presentation

- [ ] `docs/midterm_results.md`: every result with its file, method, coverage and limitations
- [ ] Slides: tp2/tp2.1 numbers (the current slides show tp1), the new algorithms, and a **plan-deviation slide** (no ring yet → reference board plus public-data validation)
- [ ] Demo script with a replay-mode fallback in case the hardware fails on the day
- [ ] Code freeze 5 Dec; rehearse
