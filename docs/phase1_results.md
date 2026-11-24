# BTP Phase-I: results the report may quote

Frozen 23 Nov 2026 at tag `phase1-report`; section 10 (WESAD) added 24 Nov 2026 at tag
`phase1-report-v2`, which the report cites. Nothing else changed between the two tags. This file lists every result the Phase-I report may
quote. Each entry gives the figure, the file it comes from, the method, the data set, the
coverage or rejection rate, and its main limitation. **Every figure here was copied from the file
named beside it. None was recalled.** If a figure is not in this file, it is not ready to be
quoted. If a file and this page disagree, the file is right; re-run the script named in its
header and correct this page.

Conventions, from `CLAUDE.md`:

- Se (sensitivity) and P+ (positive predictivity) are always reported separately, with the
  rejection rate whenever a quality gate is used. No result is "accuracy".
- Every HRV figure carries its **coverage**: accepted NN intervals ÷ all inter-beat intervals.
- **Development** data was used to set parameters. **Held-out** data was run once, after the
  parameters were frozen, and nothing was changed in response. Each entry says which kind it is.
- "Causal" is the phone's filter. "Zero-phase" is the offline `filtfilt` filter.
- Two boards were used for our own recordings: the **ring board** (ESP32-C3 SuperMini) and the
  **reference board** (ESP32-WROOM-32, custom PCB). They run the same `sketch.ino`. In dual03 the
  ring board was on the **chest** and the reference board on the **fingers** (file names
  `..._c3chest_wroomfinger_ring.csv` / `_ref.csv`). No ring form factor exists yet.
- The shipped beat timing point is **tp3** (13 Nov 2026). Results labelled tp2 or tp2.1 come
  from earlier versions and are marked as such.

---

## 1. Acquisition

### 1.1 Serial link integrity, both boards, no electrodes

- **Figure:** ring board 44,548 samples, reference board 44,545; **0 missing, 0 gaps,
  0 duplicates, 0 backward jumps, 0 malformed rows** over 174.61 s of host time.
- **Source:** `analysis/integrity_20260929_152557_linktest_noelectrodes.txt`
  (`./integrity.py` on `captures/20260929_152557_linktest_noelectrodes_{ring,ref}.csv`).
- **Method:** checks sample-index continuity on the host CSV, not the firmware's counters.
- **Data:** one 3-minute dual capture with no electrodes attached, 29 Sep 2026.
- **Coverage:** 100% of samples.
- **Limitation:** one capture, no electrodes, over USB serial, not BLE. Host-clock rates in the
  same file (255.12 / 255.11 SPS whole capture, 256.04 SPS middle 80%) include USB buffering and
  host timing. **They are not oscillator rates and must not be quoted as such.**

### 1.2 ECG amplitude (open issue: do not quote millivolts)

- **Figure:** median-beat QRS peak-to-peak 270 codes at the chest (ring board) and 100 codes at
  the fingers (reference board); QRS-to-noise ratio 19 and 16.
- **Source:** `analysis/amplitude_dual03.txt` (`./amplitude_check.py`); discussion in
  `docs/amplitude_investigation.md`.
- **Method:** raw codes, ETAG 0/2 only, first 10 s dropped.
- **Data:** dual03 (29 Sep 2026), one person, 105.6 s.
- **Limitation:** on the nominal scale (2621.44 codes/mV, **not verified**) these are 103 µV
  and 38 µV, about ten times smaller than expected for these leads. The cause is unresolved. The
  leading suspect is the calibration sources that `begin()` routes onto the inputs (datasheet
  check #21). **Quote codes and ratios only, never millivolts,** until the bench A/B and `c`
  calibration test in `docs/amplitude_investigation.md` have been run.

---

## 2. Finger against chest, same person, same time (dual03)

### 2.1 Beat and heart-rate agreement (tp2)

- **Figure:** 179 beats at each site; **Se 99.44%, P+ 99.44%** (178 matched, 1 missed,
  1 extra). HR bias **+0.03 bpm**, LoA −0.10 to +0.15 bpm, ICC 0.9998, CCC 0.9997. RR bias
  +0.00 ms, LoA −1.57 to +1.58 ms on 169 intervals (8 flagged out). RMSSD on the cleaned NN series:
  chest 18.1 ms, finger 18.0 ms.
- **Source:** `analysis/agreement_20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref_tp2.txt`
  (`./agreement.py`; settings fs 256, mains 50, window 10 s, tolerance 150 ms, skip 10 s,
  max offset 5 s).
- **Method:** integrity check, software alignment from the beat trains (offset −17 ms), beat
  matching within 150 ms, Bland–Altman on heart rate and RR.
- **Data:** one subject, seated at rest, hands still, 104.8 s shared span. Both channels had
  0 missing, 0 gaps and 0 duplicates.
- **Coverage:** 169 RR pairs used; 8 flagged out.
- **Limitation:** **one subject, one posture, 105 s**: a feasibility result, not a validation
  study. The timing point is tp2, not the shipped tp3 (see 2.2). The file also prints a drift
  estimate (−16.7 ± 7.3 ppm). **Do not quote it**: at this record length the fit has no power,
  and the estimate changed sign when one setting was varied (`CLAUDE.md`, status). The −17 ms
  offset is host serial latency, not physiology. Electrode polarity was reversed (lead −II),
  which does not affect timing but blocks any morphology claim.

### 2.2 The same comparison with the shipped timing point (tp3)

- **Figure:** causal filter: 180 beats per site, all 180 matched; RR LoA **−1.8 to +1.8 ms**
  (n 166); RMSSD chest 18.3 ms (coverage 92%), finger 17.9 ms (94%). Zero-phase: RR LoA −1.8 to
  +1.8 ms (n 170); RMSSD 18.0 ms (94%) and 17.9 ms (94%). tp2.1 on the same data: LoA ±1.7 ms
  causal, ±1.6 ms zero-phase.
- **Source:** `analysis/tp3_own_recordings.txt` (`./evaluate_tp3.py own`).
- **Method:** as `fiducial.py dual`: skip 10 s, longest unbroken run of each channel, RR pairs
  only where neither beat is flagged at either site.
- **Data and limitation:** as 2.1.

---

## 3. Beat detection: ANSI/AAMI EC57 on MIT-BIH

All runs: 150 ms tolerance, resampled to 256 Hz, MLII where present, zero-phase benchmark filter.

### 3.1 Held-out, run once (tp2.1, 31 Oct 2026)

| Set | Gate | Se | P+ | Rejected |
|---|---|---|---|---|
| 32 non-paced records | none | **99.78%** | **99.32%** | – |
| 32 non-paced records | bSQI 0.9 | 99.82% | 99.89% | 2.4% of recording time |
| 4 paced records (102 104 107 217) | none | 99.55% | 99.24% | – |
| 4 paced records | bSQI 0.9 | 99.52% | 99.37% | 4.0% |

- **Source:** `analysis/heldout_ec57_tp2.1.txt` (parameters frozen in commit `da603e2`; the file
  confirms the frozen files were unchanged).
- **Data:** the 36 MIT-BIH records that were not used in development. Paced records are
  reported separately, as EC57 excludes them.
- **Limitation:** record 207 has P+ 80.88%. It contains ventricular flutter, which this benchmark
  scores and EC57 practice may exclude; nothing was changed. **This set has been used, and all
  48 MIT-BIH records have been development data since 13 Nov 2026.** Quote this as the held-out
  result for tp2.1 only.

### 3.2 After the tp3 port (detection unchanged)

| Set | Timing | Gate | Se | P+ | Rejected |
|---|---|---|---|---|---|
| 12 development records | tp3 | none | 99.49% | 98.29% | – |
| 12 development records | tp3 | bSQI 0.9 | 99.69% | 99.55% | 6.1% |
| 36 former held-out records | tp3 | none | 99.76% | 99.31% | – |
| 36 former held-out records | tp3 | bSQI 0.9 | 99.78% | 99.84% | 2.6% |
| 36 former held-out records | tp2.1 | none | 99.75% | 99.31% | – |

- **Source:** `analysis/ec57_benchmark_tp3.txt` (`./benchmark_mitdb.py --method ours
  --fs-target 256 --lead mlii --timing tp3|tp2.1`).
- **Limitation:** this shows that the tp3 port did not move detection. It is **not** a
  held-out result, because the 36 records were spent by then. Ungated P+ on the 12 development
  records fails the 99% gate because of record 108 (P+ 83.52%).

---

## 4. Beat timing and HRV

### 4.1 Beat timing, held-out: INCART, run once (tp3 against tp2.1)

- **Figure (causal, 75 records):** median coverage **56% → 68%**; records with pipeline NN
  coverage under 50%: 29 → 15; RMSSD error against the annotations, median [range]
  −0.50 [−32.92, +18.21] ms → **−0.69 [−8.80, +0.87] ms**; mean absolute error 2.08 → 1.22 ms;
  RMSSD withheld on 9 → 3 records. Over the 32 patients: patients with NN coverage under 50%
  **11 → 2**. Detection Se/P+ 99.76/98.81% → 99.77/98.82%.
- **Zero-phase:** coverage 55% → 68%; RMSSD error −0.60 [−12.85, +27.73] → −0.65 [−8.86, +1.07] ms;
  mean absolute error 2.68 → 1.19 ms.
- **Source:** `analysis/tp3_incart_heldout.txt` (`./evaluate_tp3.py incart`; tp3 frozen in
  `tp3_candidate.json` on 13 Nov 2026 before the run).
- **Method:** the same tp2.1 beats, retimed by tp3; RMSSD per record compared with the RMSSD of
  the annotated beats.
- **Data:** St Petersburg INCART 12-lead database, lead II, 75 records from 32 patients; held out
  and now spent.
- **Limitation:** INCART's beat positions were placed by an algorithm and not corrected by hand,
  so these errors compare the two timing points rather than measure absolute accuracy. tp3 was
  worse on patient 24 (coverage 90% → 48% on one record), diagnosed in
  `analysis/tp3_diagnosis_incart_patient24.txt` and left unchanged. The tp3 port was checked
  against the evaluated candidate: identical in 100 of 100 runs, largest position difference
  5.8e-11 samples (`analysis/tp3_port_check.txt`).

### 4.2 HRV arithmetic against neurokit2, MIT-BIH

- **Figure (held-out 32 non-paced, 300 s windows, as shipped):** RMSSD, SDNN, SD1 and SD2
  differ from neurokit2 by **0** on every reported window (182, 178, 182 and 178 of 192 windows
  reported). pNN50 is identical with the same denominator. LF/HF: median relative difference
  0.82% (no holes) and 0.62% (holes), maximum 3.2% and 4.7%; on neurokit2's own frequency grid
  maximum 0.03% and 0.15%. DFA α1 identical on windows without holes (116 of 192 reported).
  Sample entropy identical without holes (127 of 192).
- **Source:** `analysis/hrv_vs_neurokit_mitdb_heldout.txt`, `analysis/hrv_vs_neurokit_mitdb_dev.txt`
  (`./validate_hrv_neurokit.py`, neurokit2 0.2.13, numpy 2.4.2, scipy 1.17.0).
- **Method:** our functions and neurokit2 on the **same** NN series, so only the arithmetic is
  compared.
- **Coverage:** windows reported per measure as above; LF, HF and LF/HF were reported in 67 of
  192 windows, because they need 95% coverage. Per-record NN coverage is listed in the file.
- **Limitation:** this checks arithmetic, not whether the beats are in the right place or what
  the numbers mean physiologically. Run with tp2.1 beats. DFA α1 uses boxes 4–16; neurokit2's
  default (4–11) gives a different number on the same data.

### 4.3 HRV minimum windows

- **What may be quoted:** the enforced minimums (RMSSD, pNN50 and SD1: 60 s of valid NN time and
  30 intervals; SDNN and SD2: 120 s; HF: 60 s at ≥95% coverage; LF and LF/HF: 120 s at ≥95%;
  DFA α1: 120 s and 200 intervals in runs; sample entropy: 180 s and 200 templates).
- **Source:** `algorithms/config.json`, `docs/hrv_minimum_windows.md`,
  `analysis/hrv_min_window_simulation.txt`.
- **Limitation:** a 2-minute session cannot reach the 120 s of valid NN time that SDNN, SD2, LF/HF
  and DFA α1 need, which is why the app uses 3- and 5-minute sessions.

---

## 5. ECG-derived breathing rate: BIDMC held-out, run once

- **Figure (fused rate, causal filter, gate on):** reported in **1,282 of 3,141 reference
  windows (41%)**; MAE pooled **0.50 breaths/min**, bias +0.17, LoA −2.9 to +3.3; 96% of
  reported windows within 2 breaths/min; per-subject MAE median 0.43 [IQR 0.33, 0.92] over 21 of
  23 subjects; per-subject coverage median 16.26% [IQR 4.23, 79.69]. Zero-phase: 38% reported,
  MAE 0.46.
- **Why RSA is never reported alone:** RSA on its own, causal, gate on: MAE 5.35 breaths/min at
  43% reported. R amplitude alone: MAE 1.04 at 55%.
- **Source:** `analysis/breathing_bidmc_heldout.txt` (`./validate_breathing_bidmc.py --set
  heldout`; settings frozen in commit `467881d` before the run). Development figures:
  `analysis/breathing_bidmc_dev.txt` (fused, causal: 39% reported, MAE 0.46).
- **Method:** 32 s windows every 3 s; reference = the mean of both annotators where they agree
  within 2 breaths/min (77.6% of windows); RSA and R-amplitude spectra by Lomb–Scargle, fused by
  the `agree_or_ramp` rule.
- **Data:** BIDMC, split by subject: 23 held-out subjects, 27 recordings, lead II, intensive-care
  patients. Reference rates 11.3–25.8 breaths/min.
- **Limitation:** **coverage is low and very uneven between subjects** (median 16%). No slow
  breathing (6/min) is in the held-out data, so the guided-breathing use case is untested. The
  data are hospital recordings, not ours. The held-out subjects are now spent.

### 5.1 Session-level rules (development data only)

- **Figure:** with `hr_min_intervals` 60, `breathing_min_windows` 5 and `breathing_max_range_bpm`
  6, 61% of 3-minute BIDMC development sessions get a breathing rate (causal; MAE 0.44
  breaths/min, none off by more than 2).
- **Source:** `analysis/session_rules_dev.txt` (`./derive_session_rules.py`).
- **Limitation:** derived on development data and **not checked on held-out data**.

---

## 6. Ventricular ectopic beats (class V): MIT-BIH, de Chazal split

| Set | Filter | Se | P+ | F1 | Coverage | End-to-end Se |
|---|---|---|---|---|---|---|
| DS1 (tuned on), 22 records | causal | 89.13% | 80.27% | 84.47 | 97.0% | 80.78% |
| DS2 (run once), 22 records | causal | **88.36%** | **82.67%** | 85.42 | 98.6% | 86.06% |
| DS2 | zero-phase | 89.61% | 81.27% | 85.23 | 98.8% | 87.27% |

- **Source:** `analysis/ectopic_mitdb_ds1.txt`, `analysis/ectopic_mitdb_ds2.txt`
  (`./validate_ectopic_mitdb.py`; settings frozen 13 Nov 2026 in `algorithms/config.json`).
- **Method:** template correlation against the wearer's recent normal beats, plus prematurity.
  AAMI class V = V, E; 150 ms matching; tp3 beats.
- **Coverage:** share of annotated beats that were detected and judged (column above).
  End-to-end Se counts undetected and undecided V beats as missed.
- **Limitation:** **DS2 is not truly held out**: nothing in the ectopic rule was tuned on it, but
  every MIT-BIH record is development data for the detector underneath. Record 222 has no V beats
  and gets 384 false V (causal). The **S label is not usable** (DS2 P+ 23.3%) and must not be
  quoted as a result. Python only; not on the phone.

---

## 7. AF screening (30 s windows)

### 7.1 Development: PhysioNet/CinC 2017, cross-validated by recording

- **Figure:** F1 N 0.871 ± 0.005, **A 0.735 ± 0.027**, O 0.644 ± 0.014, noisy 0.531 ± 0.048;
  mean of N, A and O 0.750. As a screen, class A: Se 74.0%, Sp 97.8% on the 96.2% of
  recordings given a rhythm label.
- **Source:** `analysis/af_cinc_cv.txt` (`./validate_af.py freeze`; model af1 frozen 13 Nov 2026).
- **Data:** 8,528 recordings, first 30 s each, causal filter; 5 folds × 3 repeats.
- **Limitation:** CinC publishes no patient identifiers, so the folds are by recording and the
  figures **may be optimistic**. The challenge's published 0.83 was on a hidden test set and is not
  comparable.

### 7.2 External test: MIT-BIH Atrial Fibrillation Database, run once

- **Figure:** **Se 92.22%, Sp 96.80% at 97.16% coverage** of windows (AF windows 94.04% decided,
  non-AF 99.23%). End to end, Se 86.72% of all AF windows, and 3.18% of all non-AF windows labelled A.
  Per patient (with 20 or more decided windows): Se median 98.1%, range 76.8–100.0% (18 patients);
  Sp median 99.8%, range 73.1–100.0% (21 patients).
- **Source:** `analysis/af_afdb_external.txt` (`./validate_af.py afdb`, commit `08d5bd9`).
- **Data:** 23 patients, 28,104 windows of 30 s; 10,952 AF, 16,430 non-AF; each window from a cold start.
- **Limitation:** P+ 94.79% holds only at this database's mix (40% of windows are AF) and would be
  far lower in screening. Atrial flutter is mostly missed (40 of 185 windows labelled A). Windows
  with a rhythm change are excluded from Se/Sp. The worst patients were not investigated. No
  session-level rule, no handling of lost samples, not on the phone.

### 7.3 Our own recordings (labels only)

- **Figure:** 9 windows judged: N 4, O 4, A 0, not decided 1.
- **Source:** `analysis/af_own_recordings.txt`.
- **Limitation:** **there is no rhythm reference**, so this is a count of labels, not a
  false-alarm rate. Any window with a lost sample is left out (all 7 of tb01). The O label fires on
  a person presumed healthy, so only "A or not A" may be shown.

---

## 8. Signal quality gate (sqi2 artifact check)

- **Figure (through the app's own pipeline):** tb02's first 42 s (electrode settling) go from
  GOOD 47.8% to **2.5%** of verdicts; tb02 after 45 s, dual03 chest, dual03 finger and dual02 are
  unchanged (e.g. tb02 after 45 s GOOD 94.1% before and after). On development data, at the shipped
  setting, the check turned 95.00% of the 20 old-GOOD settling seconds of tb02 to POOR, and 0.00%
  (as printed, rounded) of the 69,088 old-GOOD MIT-BIH seconds and of the 11,440 clean Noise Stress
  Test seconds.
- **Source:** `analysis/app_quality_gate_replay.txt` (`QualityGateReplayTest`),
  `analysis/sqi_artifact_dev.txt` (`./develop_sqi_artifact.py`).
- **Method:** 1 s blocks; a block whose swing exceeds 4× the median swing of the last 30 is an
  artifact; POOR for it and the next 9.
- **Limitation:** all development data; it rests on one settling episode and one burst. dual03's
  finger channel is GOOD only 57.3% of the time in the app's pipeline (kurtosis near its
  threshold). **The kurtosis and band-share thresholds are still not calibrated on our hardware.**

---

## 9. Phone app

### 9.1 Session report reproduces the reference pipeline (replay)

- **Figure:** on the phone (SM-A566E) replaying tb02, the 3-minute session gave 223 beats, HR 77,
  RMSSD 35.35 ms, pNN50 14.88, SD1 25.04; SDNN, SD2, LF, HF and breathing withheld. The JVM
  pipeline fed the same packets gave identical values (HR 77.087 on 220 intervals, coverage 0.991;
  SD1 on 121 intervals, coverage 0.6126).
- **Source:** `analysis/app_phone_replay_tb02.txt`.
- **Limitation:** replay of a recorded file (debug APK built from `d1eee62`, before the tp3 port).
  **Not run live with a ring board.**

### 9.2 Live heart rate

- **Figure:** `LiveHeartRateTest`, against an independent NeuroKit2 reference: **0 moments more
  than 5 bpm off** on dual03 (374 clean-reference moments shown) and tb02 (595). The old display
  failed that check at 63 and 37 moments.
- **Source:** `analysis/app_live_hr.txt`.
- **Limitation:** two recordings, replayed on the JVM.

### 9.3 Parity between phone and Python

- **What may be quoted:** the beat detector, HRV, session measures and quality gate on the phone
  are pinned to their Python references by parity unit tests (`BeatDetectorParityTest`,
  `HrvParityTest`, `SessionParityTest`, `LiveHrvParityTest`, `SignalQualityParityTest`). The test
  counts and outcomes at this tag are in `analysis/phase1_test_run.txt`: Python 117 passed
  (`tests/`) and 4 of 4 (`test_capture_sensors.py`); Android 156 tests, 0 failures, 6 skipped
  (screenshots that need a MIT-BIH replay asset which is never committed).
- **Limitation:** the parity fixtures are real recordings, which never reach the new zero-variance
  guard in `algorithms/breathing.py` (23 Nov 2026). The phone's `Breathing.kt` does not have that
  guard; on a constant series the two could disagree.

---

## 10. Multi-sensor arousal: WESAD, stress against rest (run once)

| Model | Bal. acc. [95% interval] | Se | Sp | Rejected: stress / baseline |
|---|---|---|---|---|
| All four (chest ECG + wrist BVP, EDA, TEMP) | **96.1% [91.8, 100.0]** | 92.2% | 100.0% | 13.1% / 5.2% |
| Wrist only (BVP, EDA, TEMP) | **93.3% [84.2, 99.3]** | 88.5% | 98.0% | 13.1% / 5.2% |
| EDA alone | 87.2% [78.0, 95.3] | 80.1% | 94.3% | 0% / 0% |
| ECG alone (time-domain HRV) | 86.0% [76.1, 94.7] | 82.5% | 89.5% | 0% / 0% |
| BVP alone | 81.6% [71.9, 90.3] | 74.8% | 88.4% | 13.1% / 5.2% |
| Temperature alone | 64.9% [53.5, 76.8] | 54.2% | 75.7% | 0% / 0% |

- **Task:** second half of the baseline against stress, leave-one-subject-out, pooled over
  windows; intervals are a bootstrap over subjects (2000 resamples). Scores are over **classified
  windows only**: a window is classified only when every feature of its model was reported, so read
  them with the rejection column. Per subject, balanced accuracy median [min, max]: wrist only
  100.0 [50.0, 100.0], all four 100.0 [78.9, 100.0].
- **Binary task of Schmidt et al. (stress against baseline + amusement, models retrained):** wrist
  only accuracy 90.4% [83.7, 96.3], F1 90.2, balanced accuracy 90.0%, with 13.1% of stress and 10.5%
  of non-stress windows rejected; all four 89.0%; ECG 85.3%; EDA 88.3%. Theirs: 93.12% (LDA, all
  chest signals), wrist at best 88.33% (random forest). Windows, normalisation, classifier and
  rejection all differ, so a figure above or below theirs is **not** described as beating or
  missing it.
- **Ablation (descriptive):** removing wrist EDA from all four drops balanced accuracy to 83.8%;
  removing ECG gives 93.3%, removing BVP 98.6%, removing TEMP 96.1%. With 15 subjects no difference
  between modalities is called significant.
- **Source:** `analysis/wesad_evaluation.txt` (`./wesad_evaluate.py`, code `fb1fa5c`; settings in the
  `wesad` and `arousal` blocks of `algorithms/config.json`, frozen 16 Nov 2026).
- **Method:** 180 s windows every 30 s; ECG time-domain HRV (causal filter, tp3), wrist pulse rate
  and amplitude, EDA tonic level, slope and skin-conductance responses (cvxEDA), wrist temperature
  slope; z-scored against each subject's reference half of the baseline; logistic regression
  (C 1, balanced class weights, threshold 0.5).
- **Pre-specification:** the plan (`docs/wesad_plan.md`) was frozen on 16 Nov 2026, before any WESAD
  signal was read. Two amendments (ECG-time in place of ECG-full; BVP rate and amplitude only) were
  made after a pilot on S2 and S3 and **approved before any classification metric was computed**
  (amendment log, 23 Nov 2026).
- **Data:** WESAD (Schmidt et al. 2018), 15 subjects; 251 stress and 210 baseline windows.
- **Limitation:** WESAD is **development data** for the PPG, EDA and temperature code: leave one
  subject out protects the classifier, not the feature code. Windows overlap by 150 s and are not
  independent; the subject is the unit of inference. The signals come from WESAD's chest and wrist
  devices, not from our boards; the held-out test is our own protocol recordings, not yet made.
  Wrist pulses are poorly locked to ECG beats outside still periods (section 9 of the file), so
  pulse-rate variability is not in the primary models.

---

## 11. Not ready to quote

These have **no result** yet, or their result must not be stated as a finding:

| Item | State | Where |
|---|---|---|
| Oscillator drift between the boards | Not measured: SYNC is not wired and 105 s gives the fit no power | `CLAUDE.md`, status |
| ECG amplitude in millivolts | Scale unverified; signal about 10× low | 1.2 |
| Anything morphological (ST, P, T) | Polarity reversed (lead −II) in every capture so far | `CLAUDE.md`, status |
| Any measurement on a ring-shaped device | None exists; all own recordings are from the reference and test boards | – |
| Live phone + board session | Not run | `android_app/LIVE_TEST.md` |
| PPG, GSR, temperature, IMU motion | Firmware streams exist; no validated result | `fw` branch, `docs/bench_session_1.md` |
| WESAD arousal index on our own hardware | WESAD result in 10; no recording from our boards | `docs/wesad_plan.md` |
| S (supraventricular) ectopic label | P+ 23% | 6 |
| AF "other rhythm" label | Fires on a presumed-healthy wearer | 7.3 |
| Quality thresholds (kSQI, pSQI) | From the literature, not calibrated | 8 |
| tp1 figures on the current slides | Superseded by tp2/tp3 | `docs/Finger_vs_Chest_ECG_Results.pptx` |
