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
- 13 Nov, **for App:** `algorithms/config.json` now has the `session` block (`hr_min_intervals` 60, `breathing_min_windows` 5, `breathing_max_range_bpm` 6; `analysis/session_rules_dev.txt`, development data only). `AlgorithmsConfigTest` will fail until `SessionRules` takes them. 30 intervals would do for heart rate in sinus rhythm; 60 is what arrhythmic sessions need.
- 13 Nov: biphasic-QRS coverage. Candidate timing point **tp3** (`tp3_candidate.py`, frozen in `tp3_candidate.json`, **not ported**): development on all 48 MIT-BIH records, now all development data; held-out on INCART, run once (`analysis/tp3_incart_heldout.txt`): median coverage 56% → 68%, patients under 50% pipeline coverage 11 → 2, mean absolute RMSSD error 2.08 → 1.22 ms. Worse on one patient. **Waiting for review before any port.** `docs/explained/algo.md`
- 13 Nov, after review: **tp3 ported** into `pan_tompkins.py` and `BeatDetector.kt` (`tp2_config.json` version tp3). Shipped detector identical to the evaluated candidate on 100 of 100 runs (`analysis/tp3_port_check.txt`); EC57 Se/P+ unchanged (`analysis/ec57_benchmark_tp3.txt`); 147 Android unit tests pass on regenerated fixtures. The patient-24 regression is diagnosed and recorded as a known limitation (`analysis/tp3_diagnosis_incart_patient24.txt`). `algo` contains `app` as of this port. **For App:** merge `algo` before continuing; `SessionRules` now take 60 / 5 / 6 from the config, and `docs/explained/app.md` carries a dated note. Next held-out data for beat timing: our recordings after the clip swap.
- 13 Nov, A1 housekeeping done: `requirements.txt` (with astropy), WESAD marked usable for scientific, non-commercial use with credit (`docs/datasets.md`), Billman 2013 cited for LF/HF and Peng et al. 1995 confirmed for the DFA α1 box range 4–16 (`docs/hrv_minimum_windows.md`), push rule in CLAUDE.md.
- 13 Nov: AF screening (week 2 item below) **not started**. Its brief builds on an ectopic-beat count from an earlier task that this branch does not have, and running the CinC held-out split without that feature would spend the split. Also found: CinC 2017 publishes no patient identifiers, so a patient-wise split cannot be made from the public files; and the published 0.83 is on a hidden test set, not on anything we can hold out.

### You
- [ ] Answer: sensor wiring, midterm date, whether Phase 2 (SoC) is assessed, ethics status
- [ ] Send the current State of the Art section or report template to the review chat
- [ ] **Bench session 1** (end of week): flash both boards, swap clips, calibration test, 10-min dual capture with the phone live, one check per sensor

## Week 2 (17–23 Nov): rhythm, sensors, motion

### Algorithms
- [ ] Bench session 1 analysed: amplitude (calibration test), 10-min HRV finger vs chest, oscillator drift, upright polarity
- [x] Ectopic beats: template correlation plus prematurity, MIT-BIH inter-patient split (de Chazal DS1/DS2), Se/P+ for V beats
  - 13 Nov: `algorithms/ectopic.py`, settings frozen in `algorithms/config.json` (`ectopic`) after tuning on DS1. Class V, causal filter: DS1 Se 89.1% / P+ 80.3% at 97.0% coverage; DS2 (run once) Se 88.4% / P+ 82.7% at 98.6% (`analysis/ectopic_mitdb_ds1.txt`, `..._ds2.txt`). **DS2 is not truly held out**: all 48 MIT-BIH records are development data for the detector. The S (early, normal shape) label has P+ 23% and is not usable. Python only; not ported.
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
  - 12 Nov, started early: **3-min** session (a 2-min one cannot hold SDNN/LF, `docs/hrv_minimum_windows.md`) plus a 5-min extended one for DFA α1 and sample entropy. Two-layer report (HR, RMSSD, breathing with "usual" after 3 live sessions; all other measures collapsible; tap for a one-line explanation), each measure "—" with its reason below its minimum. Rhythm, ectopic count, motion and arousal are hidden slots. Run end to end on the phone (SM-A566E) from a tb02 replay; the report matches the JVM pipeline exactly (`analysis/app_phone_replay_tb02.txt`, `android_app/screenshots/phone/`). Not yet run with a live ring. `docs/explained/app.md`
  - 13 Nov: merged tp3 and the `session` rules from `algorithms/config.json` (60 intervals, 5 windows, 6 breaths/min; no longer provisional); tb02's report now at 81.8% NN coverage with SDNN and SD2. Live heart rate fixed: the screens showed the detector's 8-interval threshold window (27 and 101 bpm on a GOOD tb02 replay); now `LiveHeartRate.kt`, 0 moments more than 5 bpm off an independent reference on tb02 and dual03 (`LiveHeartRateTest`, `analysis/app_live_hr.txt`)
- [x] Guided-breathing screen with live HRV (breathing at 6/min)
  - 12 Nov: pacer 6/min, live RMSSD (90 s), live breathing rate (32 s) and beat-to-beat HR curve with in-breaths shaded; parity-tested (`LiveHrvParityTest`). Rendered from replay only; not yet run on the phone, and whether the RSA swing shows on the ring is for bench session 2
- [ ] Session history stored on the phone (Room), with trends against a personal baseline
  - 12 Nov: Room storage and a History screen with per-measure trends by date done; the baseline is the median and range of earlier live sessions (arousal-vs-baseline is the Algorithms item)
- [x] Every ported algorithm has a parity test against its Python reference (12 Nov: `HrvParityTest`, `SessionParityTest` (incl. breathing), `AlgorithmsConfigTest`; fixtures `make_session_fixtures.py`)

### Algorithms
- [ ] Arousal index: HRV, GSR, temperature and PPG features z-scored against the wearer's baseline; leave-one-day-out evaluation on the protocol data; per-feature ablation

### You
- [ ] State of the Art rewrite, drafted with the review chat

## Week 4 (1–7 Dec): evaluation and presentation

- [ ] `docs/midterm_results.md`: every result with its file, method, coverage and limitations
- [ ] Slides: tp2/tp2.1 numbers (the current slides show tp1), the new algorithms, and a **plan-deviation slide** (no ring yet → reference board plus public-data validation)
- [ ] Demo script with a replay-mode fallback in case the hardware fails on the day
- [ ] Code freeze 5 Dec; rehearse
