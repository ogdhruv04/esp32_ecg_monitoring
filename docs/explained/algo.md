# The algorithms, explained

What the `algorithms/` package computes from the detector's beats, what each number needs before
it is shown, and how each was checked. Written 13 Nov 2026 on the `algo` branch. The companion
for the phone side is `docs/explained/app.md` (on the `app` branch). Every figure here comes from
a file in `analysis/`, named next to it.

## From beats to an NN series

The beat detector (`pan_tompkins.py`, timing point tp3) gives each beat a position and a flag. A flagged
beat is one whose position could not be trusted. The package turns the beats into an **NN
series**: one entry per beat-to-beat interval, with a hole wherever the interval is unusable
(a flagged or searched-back beat at either end, lost samples in between, outside 300–2000 ms, or
rejected by the 20% rule). Two things follow from keeping the holes:

- **Coverage** is well defined: accepted intervals ÷ all intervals. It travels with every result.
- **Nothing crosses a hole.** Successive differences, Poincaré pairs, DFA boxes and entropy
  templates are only taken inside runs of consecutive accepted intervals.

## Every measure can say "no"

Each measure returns a value or a reason. It is withheld when the window holds too little data;
the minimums are in `algorithms/config.json` and explained in `docs/hrv_minimum_windows.md`.
"Data" means the summed length of accepted intervals, not clock time.

| Measure | Needs |
|---|---|
| RMSSD, pNN50, SD1 | 60 s of valid NN time, 30 intervals |
| SDNN, SD2 | 120 s |
| HF | 60 s, coverage ≥ 95%, heart rate ≥ 48 bpm |
| LF, LF/HF | 120 s, coverage ≥ 95% |
| DFA α1 | 120 s and 200 intervals in runs of 16 or more |
| Sample entropy | 180 s and 200 templates |

The 95% rule exists because missing beats lift a Lomb–Scargle spectrum: at 90% coverage HF read
16–30% high in simulation (`analysis/hrv_min_window_simulation.txt`).

**Checked against neurokit2** on the same NN series (`analysis/hrv_vs_neurokit_mitdb_dev.txt`,
`..._heldout.txt`): RMSSD, SDNN, SD1 and SD2 are identical; DFA α1 and sample entropy are identical
on windows without holes; LF/HF agrees within 3.4% as shipped and within 0.03% on neurokit2's own
frequency grid. That is a check of arithmetic. It says nothing about whether the beats are in the
right place or what the numbers mean physiologically.

## Breathing rate from the ECG

Breathing changes two things the ECG shows: the beat-to-beat interval (RSA) and the height of the
R wave. Each gives a series sampled once per beat. In a 32 s window the package takes the
spectrum of each and reports the **fused** rate when the two agree within 3 breaths/min, or when
the R-amplitude peak alone is strong. RSA is never reported by itself.

On the BIDMC held-out subjects (`analysis/breathing_bidmc_heldout.txt`, phone's filter): a rate
in **41% of windows**, mean error 0.50 breaths/min. RSA alone was wrong by 5.35 breaths/min on
average there, which is why it is not trusted alone. Those are elderly intensive-care patients on
lead II; slow breathing (6/min) was not in the held-out data. Bench session 2 is the real test.

## Session rules (13 Nov)

A session is one 3- or 5-minute recording. Two of its numbers are summaries of many smaller
results, and their rules are now in `algorithms/config.json` under `session`
(`analysis/session_rules_dev.txt`, development data only):

| Rule | Value | Why |
|---|---|---|
| `hr_min_intervals` | 60 | With 60 intervals scattered over a 3-minute session, 95% of heart rates were within 5 bpm of the annotated session rate (4.2 bpm on all 480 MIT-BIH sessions, arrhythmic ones included). With 30 it was 6.3 bpm. |
| `breathing_min_windows` | 5 | The smallest number at which no development session was off by more than 2 breaths/min. |
| `breathing_max_range_bpm` | 6 | The widest limit that still kept every reported session within 2 breaths/min. |

With these, 61% of 3-minute BIDMC development sessions get a breathing rate (mean error
0.44 breaths/min) and 74% of 5-minute ones. The app's provisional values were 30, 5 and 4.

Two things to know before relying on them:

- **Heart rate, 60 or 30?** 60 is what arrhythmic recordings need. In sessions that are in normal
  sinus rhythm throughout, 30 scattered intervals already gave 1.8 bpm. If the app is only meant
  for people in sinus rhythm, 30 is defensible; the file has both tables.
- **Breathing really does vary.** Inside a 3-minute session the reference's own window rates span
  a median of 2.7 breaths/min and up to 7.2. A tight spread limit rejects correct sessions.

None of this was checked on held-out data: the BIDMC held-out subjects were already spent.

## Beat timing: tp3 (shipped 13 Nov)

**The problem with tp2.1.** It timed a beat at the peak of its larger QRS lobe, so it first had
to decide which lobe is larger. When the two lobes are close in size it refused, flagged the
beat, and the recording lost its HRV. On our test-board recording `tb02`, 102 of 368 beats were
flagged under the phone's filter, 87 of them for this reason, leaving 62% coverage
(`analysis/tp3_own_recordings.txt`).

**What tp3 does.** It does not ask which lobe is the R wave. It slides the beat against the
median of the previous 16 beats and takes the shift at which they match best. The time is then
referred to one peak of that median beat, which is followed from beat to beat rather than chosen
each time. Detection is untouched: the same beats, timed differently.

**Before and after, same beats, phone's filter:**

| | tp2.1 | tp3 | File |
|---|---|---|---|
| MIT-BIH, 44 non-paced records (development): coverage, median | 57% | 82% | `analysis/tp3_mitdb48_dev.txt` |
| … records with pipeline coverage under 50% | 14 | 6 | |
| … RMSSD error against annotations, mean absolute | 0.33 ms (39 records) | 0.37 ms (43 records) | |
| INCART, 75 records, 32 patients (**held-out, run once**): coverage, median | 56% | 68% | `analysis/tp3_incart_heldout.txt` |
| … patients with pipeline coverage under 50% | 11 | 2 | |
| … RMSSD error, mean absolute | 2.08 ms (66 records) | 1.22 ms (72 records) | |
| … largest RMSSD error | 32.9 ms | 8.8 ms | |
| dual03, finger against chest: RR limits of agreement | ±1.7 ms | ±1.8 ms | `analysis/tp3_own_recordings.txt` |
| tb02: coverage | 62% | 82% | |
| BIDMC, 53 recordings: under 50% coverage | 12 | 3 | `analysis/tp3_bidmc_coverage.txt` |

On the MIT-BIH records where tp2.1 gave nothing under the phone's filter (111, 117, 215, 230),
tp3 covers 82–99% of beats with RMSSD errors between −0.12 and −2.27 ms.

**The port.** tp3 was developed offline (`tp3_candidate.py`), frozen, checked once on INCART, and
then ported unchanged into `pan_tompkins.py` and `BeatDetector.kt`. Three checks:

- The shipped detector gives exactly what was evaluated: 100 of 100 runs identical
  (`analysis/tp3_port_check.txt`).
- Beat detection did not move. On the 36 MIT-BIH records that used to be held out: Se 99.76% /
  P+ 99.31% with tp3, 99.75% / 99.31% with tp2.1. On the 12 original development records:
  99.49% / 98.29% and 99.50% / 98.30% (`analysis/ec57_benchmark_tp3.txt`).
- The phone code gives the Python positions: all 147 Android unit tests pass on regenerated
  fixtures.

tb02's 3-minute session now reports SDNN and SD2 at 81.8% coverage; LF and HF stay withheld
because coverage is under 95% (`analysis/app_session_reference.txt`).

**Known limits.**

- **A jump wider than 39 ms.** tp3 looks ±39 ms around the detector's peak. On INCART patient 24
  that peak alternates between two places 41 ms apart, so many beats found no match in range and
  were flagged: coverage fell from 90% to 48% on one record, where tp2.1 coped
  (`analysis/tp3_diagnosis_incart_patient24.txt`). This was found on held-out data and nothing
  was changed.
- **After a polarity flip, a constant offset.** If the wearer turns the ring over, the followed
  peak can settle on another lobe. Beats are then timed about 22 ms later than before. Intervals
  between beats are unaffected; absolute beat time is, which matters for pulse arrival time.
- **RMSSD slightly low:** median error −0.15 ms on MIT-BIH against −0.03 ms for tp2.1.
- **Noise is not fixed.** tb02 reaches 82%, not the 95% that LF and HF need.
- INCART's annotations were placed by an algorithm and not corrected in position, so its RMSSD
  errors compare the two timing points; they are not absolute accuracy.

INCART is now spent. The next held-out data for beat timing is our own recordings after the clip
swap at bench session 1.

## Ectopic beats (13 Nov)

A ventricular ectopic beat (a PVC) does not look like the wearer's normal beat and usually comes
early. `algorithms/ectopic.py` gives every detected beat two numbers and one label:

- **shape**: its best correlation with a template of the wearer's *normal* beats (the median of
  the last 16 beats that were themselves labelled normal, so ectopic beats do not dilute it);
- **timing**: the interval before it, divided by the usual interval between two normal beats.

| Label | Rule |
|---|---|
| V (ventricular ectopic) | correlation under 0.95 and at least 10% early, or correlation under 0.7 whatever the timing |
| S (early, normal shape) | correlation 0.97 or more and at least 15% early |
| N | everything else that could be judged |
| U (undecided) | no template yet, a gap, or no usual interval yet |

The thresholds were tuned on DS1, the 22 MIT-BIH records de Chazal et al. (2004) set aside for
training; DS2 is their 22 test records, from other patients.

| Class V, phone's filter | Se | P+ | Coverage | File |
|---|---|---|---|---|
| DS1 (tuned on) | 89.1% | 80.3% | 97.0% | `analysis/ectopic_mitdb_ds1.txt` |
| DS2 (run once, after the freeze) | 88.4% | 82.7% | 98.6% | `analysis/ectopic_mitdb_ds2.txt` |

Coverage is the share of annotated beats that were detected and judged. Counting the ventricular
beats that were not detected or not judged as missed, sensitivity on DS2 is 86.1%.

**DS2 is not truly held out.** Nothing in the ectopic rule was tuned on it, but every MIT-BIH
record is development data for the detector underneath, so read the DS2 line as "other patients
in the same database", not as an estimate for new data.

**Where it fails** (DS2, per record in the file):

- Record 222 has no ventricular beats and 384 were reported: its rhythm changes (atrial flutter,
  junctional) alter the beat's shape, and a shape under 0.7 is called V whatever the timing.
- Record 214 (left bundle branch block): 93 of 256 found. Record 105 (noise): 80 false V.
- **The S label is not usable as it stands**: 86.0% of supraventricular ectopic beats are caught,
  but only 23.3% of S labels are right. It was not tuned. Do not show an "early beats" count from it.
- In sustained bigeminy with no normal stretch, everything becomes undecided. That is reported
  as low coverage, not as a wrong count.

An **ectopic count for a session** is therefore the number of V labels, shown with its coverage,
and it will over-count in people whose normal beat changes shape.

## AF screening (13 Nov)

Atrial fibrillation makes the beat-to-beat interval irregular with no pattern. `algorithms/af.py`
looks at one **30 s window** and gives it one of four labels: N (normal), **A (AF-like)**,
O (other rhythm), ~ (cannot tell). It is a screening label, not a diagnosis: it reads beat timing
and the ectopic labels only and never looks at P waves, so it cannot tell AF from another
irregularly irregular rhythm.

- **Features** (11): mean interval, three measures of how much successive intervals differ
  (RMSSD, SD and the median successive difference, each relative to the mean interval), the
  Poincaré SD1/SD2 ratio, the turning-point ratio, a sample entropy made for short series
  (coefficient of sample entropy), and from the ectopic step the share of beats labelled V, the
  share that came early, and the share it could not judge, plus the share of beats the detector
  could not time. They use **all** detected intervals: the 20% cleaning used for HRV would remove
  exactly the irregularity looked for.
- **Each window starts cold** (filter, detector, ectopic template), because the development
  recordings are 30 s long. A cold start leaves a median 42% of the beats without an ectopic label.
- **Gate:** under 10 intervals the window is not judged ("~").
- **Model:** 100 rounds of depth-3 gradient-boosted trees, stored as plain numbers in
  `algorithms/af_model.json` (version af1, frozen 13 Nov). The rule fixed beforehand was "logistic
  regression unless the trees are more than 0.02 better in class-A F1"; they were 0.039 better
  (0.735 against 0.696). Python only; not ported.

**Development: PhysioNet/CinC 2017**, 8,528 hand-held single-lead recordings, first 30 s of each,
the phone's causal filter. Cross-validation is **by recording**: the dataset publishes no patient
identifiers, so one person's recordings can be on both sides of a fold and these figures may be
optimistic (`analysis/af_cinc_cv.txt`).

| Class | Normal | AF | Other rhythm | Noisy |
|---|---|---|---|---|
| F1 | 0.871 | 0.735 | 0.644 | 0.531 |

The mean of the first three, the challenge's own score, is 0.750. The challenge's top entries
scored 0.83, but on a hidden set of other recordings that is not public, using the waveform as
well; the two numbers are not comparable. As a screen on these recordings class A has Se 74.0% and
Sp 97.8% on the 96.2% of recordings given a rhythm label; of the false A labels, 116 are "other
rhythm" recordings and 30 are normal ones.

**The ectopic features add nothing that can be measured**: class-A F1 is 0.727 without them and
0.735 with them, and the fold-to-fold spread is 0.027. They stay in because the model was frozen
with them.

**External test: MIT-BIH Atrial Fibrillation Database** (ODC-By 1.0), 23 patients with about 10 h
each, never used in this project before, run once after the freeze (commit `08d5bd9`). 30 s
windows, each resampled to 256 Hz and processed from a cold start. A window counts as AF when the
whole of it is annotated AF, as non-AF when none of it is AF or flutter
(`analysis/af_afdb_external.txt`).

| | Windows | Result | Coverage |
|---|---|---|---|
| Sensitivity (AF windows labelled A) | 10,952 | 92.2% | 94.0% decided |
| Specificity (non-AF windows not labelled A) | 16,430 | 96.8% | 99.2% decided |

- **End to end**, counting undecided AF windows as missed, sensitivity is 86.7%, and 3.2% of all
  non-AF windows are labelled A.
- **Per patient** the median is Se 98.1% and Sp 99.8%, but the worst are far lower: Se 76.8%
  (07162), 82.8% (05121), 83.8% (04936); Sp 73.1% (06426), 74.1% (08219), 76.9% (06995). The cause
  in those patients was not looked into.
- **Atrial flutter is mostly missed**: 40 of 185 flutter windows are labelled A. Windows with a
  rhythm change inside them (528) are labelled A 37% of the time. Neither group is in the figures above.
- **P+ of 94.8% holds only for this database**, where 40% of windows are AF. In people who are
  mostly in normal rhythm, a 3% false-positive rate per window means most A labels would be false.
- It scores better here than in cross-validation. The two tasks differ (CinC has an "other
  rhythm" class that takes many AF recordings; here there are two groups); nothing here tests why.

**Our own recordings** (`analysis/af_own_recordings.txt`): 9 windows could be judged; none is
labelled A, 4 are N, 4 are O and 1 is undecided. Nobody has read the rhythm of these recordings,
so this is a count of labels, not a false-alarm rate. Two things it does show:

- **The O label fires on a person presumed healthy** (4 of 5 dual03 windows). Do not show
  "other rhythm" in the app; show A or not A.
- **A window with any lost sample is left out**, and that removed all 7 windows of tb01 and 5 of
  9 of tb02. The features can skip over a gap, but the model was never tested on windows with
  gaps. On a link that loses packets this has to be solved before the check is useful.

**Before this goes in the app:** a session holds several 30 s windows and no rule yet says how
many A labels make a session "AF-like" (that rule needs its own data); the model was developed
on cold-started windows, so the app must either process each window that way or the model must
be re-checked on a running detector; and there is no parity-tested Kotlin version.

## Data and how it is split

`docs/datasets.md` has the licences. In short: all 48 MIT-BIH records are development data from
13 Nov 2026; INCART (32 patients) is the held-out set for beat timing and has been used once;
BIDMC is split by subject (23 development, 23 held-out, both used). CinC 2017 is development data
for AF screening; the MIT-BIH Atrial Fibrillation Database was its external test and is now spent.

## Limits

- Every validation so far is on public hospital data or on a few short recordings of our own.
  Nothing here has been run on the ring.
- SDNN, SD2 and sample entropy depend on the length of the recording. Compare like with like.
- DFA α1 uses box sizes 4–16. neurokit2's default (4–11) gives a different number on the same data.
- AF screening is a per-window label validated on hospital Holter tape and hand-held recordings.
  It has no session-level rule, no handling of lost samples and no port to the phone yet.
