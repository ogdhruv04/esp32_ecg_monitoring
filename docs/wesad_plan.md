# WESAD analysis plan

**Frozen 16 Nov 2026, before any WESAD signal was read.** When this was written the archive had been
downloaded and only its documentation opened: `wesad_readme.pdf`, the 15 `SX_readme.txt` and the 15
`SX_quest.csv`. No `.pkl`, no signal and no feature had been loaded. The commit that adds this file
is the freeze; later changes go in the amendment log at the end, with a date and a reason, and never
in response to a classification result.

## 1. Purpose and what this is not

We have no bench recordings of PPG, skin conductance or temperature yet, so the PPG, EDA, temperature
and arousal algorithms are developed on WESAD. **WESAD is development data for those algorithms.**
Leave-one-subject-out testing protects the classifier from seeing the test subject; it does not turn
WESAD into held-out data for the feature code. The held-out test for our hardware is our own protocol
recordings (`docs/MIDTERM_PLAN.md`, bench session 2, leave-one-day-out).

The output is an **arousal index against the wearer's own baseline**. WESAD's labels are protocol
conditions ("baseline", "stress" = Trier Social Stress Test, "amusement", "meditation"). We report how
well the index separates the TSST condition from the baseline condition. No psychological claim.

## 2. Data, as documented by its authors

Sources: Schmidt et al., ICMI 2018 (the paper, read 16 Nov 2026) and `wesad_readme.pdf` in the archive.

- 15 subjects (S2–S11, S13–S17; S1 and S12 discarded by the authors for sensor malfunction), 12 men,
  3 women, mean age 27.5 ± 2.4 (paper §3.1).
- Chest: RespiBAN, ECG / EDA / EMG / RESP / TEMP / ACC, all 700 Hz. EDA on the rectus abdominis, TEMP on
  the sternum (paper §3.2).
- Wrist: Empatica E4 on the non-dominant hand, BVP 64 Hz, EDA 4 Hz (µS), TEMP 4 Hz (°C), ACC 32 Hz.
- `SX.pkl`: both devices and a label per chest sample (700 Hz): 0 undefined/transient, 1 baseline,
  2 stress, 3 amusement, 4 meditation, 5/6/7 to be ignored (readme §II.3).
- Protocol (paper §3.3): baseline 20 min (reading, sitting or standing), amusement 392 s (video clips),
  stress about 10 min (speech, then mental arithmetic, in front of a panel), 10 min rest, two 7-min
  meditations. Baseline is always first. Order after it, from the `SX_quest.csv` files: stress first in
  S2 S3 S6 S9 S11 S14 S16, amusement first in S4 S5 S7 S8 S10 S13 S15 S17.
- Authors' notes that matter here (`SX_readme.txt`): chest TEMP "not fully attached" throughout in S2
  and S17; S3's baseline was in a sunny workplace; S8 and S16 "felt rather cold in the room where the
  stress condition was carried out", so **the stress condition was in another room**; S6 and S15 report
  not being stressed by the TSST.

### How chest and wrist were synchronised

"RespiBAN and E4 were synchronised manually via a double tap gesture" at the start and again at the
end of the protocol (paper §3.3). The readme (§II): the wearer double-tapped the chest with the hand
wearing the E4, and "the resulting characteristic pattern in the acceleration signal" was used to align
the two recordings by hand; `SX.pkl` holds the result. The labels share the RespiBAN's start time.

Consequences:
- The two devices have independent clocks. The alignment is manual, on accelerometers sampled at 32 Hz
  (wrist; 31 ms per sample) and 700 Hz (chest). Neither source says whether the end-of-protocol tap was
  used to correct clock drift, or only the first one to set an offset.
- **Pulse arrival time cannot be validated on WESAD.** The effect of interest is tens of milliseconds;
  the alignment error is of the same order or larger, and unknown. PAT is not a feature here and no PAT
  figure will be reported as a measurement.
- What we can do, and will (analysis A2): measure the apparent delay from each ECG beat to the wrist
  pulse per condition segment and its trend over the recording. A steady trend of tens of ms over two
  hours, the same sign throughout, would be clock drift; it tells us about the alignment, not about
  physiology.
- Beat-to-beat intervals do not depend on a constant offset, so pulse-rate variability against ECG HRV
  (analysis A1) is valid.

## 3. Segments and windows

- A condition segment is the longest run of consecutive samples with one label (1, 2, 3); label 4 has
  two runs, both used. Labels 0 and 5–7 are not used.
- **Reference and evaluation halves of the baseline.** The baseline segment is cut at its midpoint in
  time. The first half is the subject's **reference segment**: it supplies the mean and sd for
  z-scoring and is never classified. The second half is the baseline class. Without this cut the
  baseline class would be normalised by itself.
- **Window: 180 s, a new window every 30 s**, each entirely inside one segment (or one half of the
  baseline). 180 s is the app's session length, and it is the shortest window in which our HRV
  minimums (`algorithms/config.json`: 120 s of valid NN time for SDNN, SD2, LF and DFA α1) can be met.
  Schmidt et al. used 60 s windows shifted by 0.25 s; in a 60 s window none of our HRV measures would
  be reported.
- Windows overlap by 150 s and are not independent. The subject is the unit of inference.

## 4. Features

Every parameter below is fixed here, from the cited source or from our existing frozen configs; none
is tuned on WESAD. Each feature is either a value or withheld for that window.

### 4.1 Chest ECG: our HRV suite
700 Hz → 256 Hz (polyphase, ×128/350) → the monitoring filter, causal as on the phone, 50 Hz notch
(`algorithms/frontend.py`) → the frozen detector (tp3, `tp2_config.json`) over the whole recording →
`NNSeries.from_beats(...).window(t0, t1)` → `algorithms.hrv`, with its minimum windows.

| Feature | Definition | Withheld when |
|---|---|---|
| `hr` | 60000 / median accepted NN, bpm | fewer than 60 accepted intervals (`session.hr_min_intervals`) |
| `ln_rmssd`, `pnn50`, `ln_sdnn`, `ln_sd2` | `algorithms.hrv_time`, `hrv_nonlinear` | the measure's own gate |
| `ln_lf`, `ln_hf` | Lomb–Scargle band power | the gate, which includes 95% coverage |
| `dfa_alpha1` | boxes 4–16 | the gate |

`ECG-full` is all eight; `ECG-time` is the first five. SD1 is left out (it is RMSSD/√2), as is
ln(LF/HF) (it is `ln_lf − ln_hf`, which a linear model already has). Sample entropy needs 180 s of
valid NN time and cannot be reported in a 180 s window.

### 4.2 Wrist BVP: beats, pulse-rate variability, pulse amplitude
- **The E4's BVP is not raw PPG.** It has no DC level, so a perfusion index (AC/DC) cannot be computed
  from it. "Perfusion" here is pulse amplitude in the device's units, meaningful only relative to the
  wearer's own baseline. A true perfusion index has to wait for the MAX30102.
- Beat detection: Elgendi et al. 2013 (PLoS ONE 8(10): e76585), their parameters: band-pass 0.5–8 Hz
  (ours: 2nd-order Butterworth, zero-phase), negative samples set to zero, squared, moving averages of
  111 ms and 667 ms, offset β = 0.02 × mean of the squared signal, blocks narrower than 111 ms rejected,
  the systolic peak is the maximum of the filtered signal in each block, peaks closer than 0.3 s merged
  (the larger kept). Own implementation in `algorithms/ppg.py`, checked against neurokit2's
  implementation of the same paper.
- Pulse time: the systolic peak, parabolic interpolation over three samples (64 Hz is 15.6 ms per
  sample). Pulse amplitude: peak minus the minimum of the filtered signal since the previous peak.
- Pulse intervals go through the same cleaning as ECG intervals (`NNSeries.from_times`:
  300–2000 ms, 20% rule). No motion gate yet: the IMU item is separate.

| Feature | Definition | Withheld when |
|---|---|---|
| `pr` | 60000 / median accepted pulse interval, /min | fewer than 60 accepted intervals |
| `ln_rmssd_p`, `ln_sdnn_p` | `algorithms.hrv_time` on the pulse intervals | the measure's own gate |
| `ln_amp` | ln of the median amplitude of pulses ending an accepted interval | fewer than 60 such pulses |

### 4.3 EDA: tonic and phasic components, skin-response count
- Wrist EDA at its native 4 Hz; chest EDA reduced to 4 Hz (polyphase, ÷175).
- Decomposition: **cvxEDA**, Greco, Valenza, Lanatà, Scilingo, Citi, *IEEE Trans Biomed Eng*
  2016;63(4):797–804 (doi 10.1109/TBME.2015.2474131), with the published defaults τ0 = 2 s, τ1 = 0.7 s,
  spline knots every 10 s, α = 8e-4, γ = 1e-2, as implemented in neurokit2 0.2.13 with cvxopt. Input:
  the whole recording, standardised (mean 0, sd 1) as the reference implementation's example does; the
  tonic and phasic outputs are converted back to µS.
- Skin conductance responses: local maxima of the phasic component at least 0.01 µS high, with
  prominence at least 0.01 µS, at least 1 s apart. 0.01 µS is the lower end of the customary minimum
  amplitude (0.01–0.05 µS; Boucsein et al., *Psychophysiology* 2012;49:1017–1034. **This range is quoted
  from memory and was not checked against the paper on 16 Nov.**) Sensitivity analysis: 0.05 µS.
- cvxEDA is an offline method over a whole recording. A streaming version for the phone is only worth
  writing if EDA earns its place in the ablation.

| Feature | Definition | Withheld when |
|---|---|---|
| `scl` | mean tonic component, µS | any sample in the window ≤ 0 µS or not finite |
| `scl_slope` | least-squares slope of the tonic component, µS/min | same |
| `scr_rate` | responses per minute | same |
| `phasic_mean` | mean phasic component, µS | same |

### 4.4 TEMP: slope
Wrist TEMP at 4 Hz; chest TEMP reduced to 4 Hz. One feature, `temp_slope`: least-squares slope over the
window, °C/min; withheld when any sample is not finite or outside 20–42 °C. Chest TEMP is withheld for
S2 and S17 (the authors' note).

The temperature **level** is deliberately not a feature: skin under a device warms for a long time
after it is put on, so the level mostly encodes time since the start, and baseline is always first.

### 4.5 Not used
EMG and RESP (we have no such sensors). ACC as a feature: posture and movement differ between
conditions by protocol, and a classifier that learned them would not be measuring arousal.

## 5. Normalisation against the subject's own baseline

For subject *s* and feature *f*: μ and σ are the mean and sd (n − 1) of *f* over the windows of the
**reference segment** in which it was reported. Fewer than 5 such windows: *f* is withheld for every
window of that subject. Then z = (x − μ) / max(σ, σ_floor), clipped to ±10, where σ_floor is half the
median σ of that feature over the **training** subjects of the fold. The floor stops a subject with an
unusually flat reference (no skin responses at all, say) from producing enormous z-scores. Nothing
else is standardised.

The reference half holds 14 windows from about 10 minutes, so about 3 independent ones: each
subject's σ is a rough estimate. That is the price of a short personal baseline and is part of what
is being tested.

## 6. Model and testing

- Logistic regression, L2 penalty with C = 1, balanced class weights, threshold 0.5
  (scikit-learn `LogisticRegression`, lbfgs). No hyper-parameter search. The arousal index is the
  model's log-odds.
- **Leave-one-subject-out** over the 15 subjects. Everything fitted (the model, σ_floor) comes from
  the 14 training subjects; the test subject contributes only their own reference-segment μ and σ,
  which a wearer's baseline recording would also provide.
- **A window is classified by a model only when every feature of that model was reported.** The rest
  are rejected, and counted.
- **Primary task: baseline (second half) against stress.**
- Reported for the stress class, never as bare accuracy: Se, Sp, P+, balanced accuracy, AUC, and the
  **rejection rate** per class. Pooled over windows with a 95% interval from a bootstrap over
  subjects (2000 resamples, seed 20261116), and per subject as median and range, with the number of
  subjects that had any classified window in each class.

### Models

| Model | Features |
|---|---|
| ECG | ECG-full (chest) |
| BVP | wrist BVP |
| EDA | wrist EDA |
| TEMP | wrist TEMP |
| **Wrist-only** | BVP + EDA + TEMP, all wrist. Closest to a ring's sensors |
| **All four** | ECG-full + wrist BVP + wrist EDA + wrist TEMP: our reference hardware's sensor set |

**Per-modality ablation:** each modality alone (the first four rows), and All-four and Wrist-only with
each of their modalities removed in turn. Because models reject different windows, every comparison is
given twice: on each model's own windows, and on the windows that every compared model classified.
The ablation is descriptive; with 15 subjects no difference between modalities will be called
significant.

## 7. Secondary analyses, also fixed now

- **B1. False alarms on other conditions.** Each fold's primary models, unchanged, applied to the test
  subject's amusement and meditation windows: share called "stress", overall and by condition order.
  This is the check on the confound in section 8.
- **B2. Stress against non-stress** (second-half baseline + amusement), the same models retrained,
  leave-one-subject-out. This is the task of Schmidt et al.; pooled accuracy and class-averaged F1
  are added here, for the comparison only.
- **B3.** ECG-time in place of ECG-full (coverage is expected to be higher).
- **B4.** Chest EDA and chest TEMP as single-modality models, for the site comparison.
- **B5.** Skin-response threshold 0.05 µS instead of 0.01 µS.
- **A1. Wrist pulse against chest ECG** (development result for the PPG code): pulses matched to ECG
  beats within ±150 ms after removing the median delay of the segment, Se and P+; per window, pulse
  rate against heart rate (bias, limits of agreement) and RMSSD from pulses against RMSSD from ECG,
  with the coverage of both, by condition.
- **A2. Synchronisation check**, as described in section 2.

## 8. Comparison with Schmidt et al. 2018, and why it is loose

Their best binary result is **93.12% accuracy, F1 91.47, LDA on all chest physiological signals**
(ECG, EDA, EMG, RESP, TEMP); wrist physiological signals gave at best 88.33% (random forest), 86.46%
with LDA (paper, Table 4). Differences from this plan:

| | Schmidt et al. | Here |
|---|---|---|
| Binary task | stress vs baseline + amusement | primary: stress vs baseline; their task is B2 |
| Chest signals | ECG, EDA, EMG, RESP, TEMP | no EMG, no RESP |
| Windows | 60 s, shifted 0.25 s | 180 s, every 30 s |
| Baseline | all 20 min is a class | first half is the reference, never classified |
| Normalisation | none described | z-score against the subject's reference |
| Classifier | LDA (and four others) | logistic regression |
| Rejected windows | none | counted, per model |
| Metric | accuracy, class-averaged F1, over windows | Se, Sp, P+, balanced accuracy, AUC, rejection |

Their 69.94% majority-class accuracy (Table 4) shows why accuracy alone is not reported here. A figure
of ours above or below 93.12% will not be described as beating or missing their result.

## 9. Known limits, stated before the results

- **Order and drift.** Baseline is always first, so time since the start separates baseline from
  stress perfectly. Any feature that drifts through a session (tonic skin conductance, as the electrodes
  settle) can score well for that reason alone. B1 and B2 are the checks: amusement and meditation are
  also later in time, and a model that only learned "later" will call them stress.
- **Room and posture.** The TSST was in another room (two subjects found it cold) and half the subjects
  stood for some conditions. Temperature slope and heart rate carry both.
- **Speech and movement** during the TSST disturb breathing, HRV and the wrist PPG. A separation
  between the conditions is a separation between everything that differed.
- 15 subjects, 12 of them men, all about 27. Two (S6, S15) said the TSST did not stress them; they stay
  in, labelled by protocol.
- The wrist is not a finger, and the E4's sensors are not ours.

## 10. Pilot (16 Nov) and what it may change

Pilot subjects: **S2 and S3**, the first two by number, chosen before any signal was read. They stay
in the full analysis.

The pilot reports: array lengths, durations and label runs; how often each feature is reported, by
condition; the reference means and sds; median z-score of each feature by condition for these two
subjects (a check on signs and units, not a result); A1 and A2 on two subjects; run time and peak
memory. **It computes no classification metric.** `wesad_evaluate.py` refuses to print one for fewer
than all 15 subjects, and the classifier code is tested on synthetic features.

After the pilot, and before the full run, this plan may be amended only for:
1. a bug, or a misreading of the data format;
2. run time or memory (6 GB limit: one worker, one subject at a time);
3. availability: a feature reported in under half of the pilot windows of either class may be moved out
   of a primary model.

Not for the size or direction of any pilot z-score, and never for a classification result.

## 11. Files

- `algorithms/wesad.py` loader; `algorithms/ppg.py`, `eda.py`, `temp.py` features; `algorithms/arousal.py`
  normalisation, model, leave-one-subject-out; settings in `algorithms/config.json` (`wesad`, `ppg`,
  `eda`, `temp`, `arousal`).
- `wesad_features.py --dir <main>/data/wesad --subjects S2 S3`: one subject at a time; per-window
  feature tables go to `<main>/data/wesad_features/` (not committed: derived from data that is for
  scientific, non-commercial use). `wesad_evaluate.py`: sections 6–7; `--pilot` for section 10.
- Reports in `analysis/wesad_*.txt`.
- Credit: Schmidt P, Reiss A, Duerichen R, Marberger C, Van Laerhoven K. Introducing WESAD, a multimodal
  dataset for Wearable Stress and Affect Detection. ICMI 2018. doi 10.1145/3242969.3242985.

## Amendment log

*(none)*
