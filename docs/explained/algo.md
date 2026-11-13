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

## Data and how it is split

`docs/datasets.md` has the licences. In short: all 48 MIT-BIH records are development data from
13 Nov 2026; INCART (32 patients) is the held-out set for beat timing and has been used once;
BIDMC is split by subject (23 development, 23 held-out, both used).

## Limits

- Every validation so far is on public hospital data or on a few short recordings of our own.
  Nothing here has been run on the ring.
- SDNN, SD2 and sample entropy depend on the length of the recording. Compare like with like.
- DFA α1 uses box sizes 4–16. neurokit2's default (4–11) gives a different number on the same data.
- AF screening has not been started (see the end-of-session note in `docs/MIDTERM_PLAN.md`).
