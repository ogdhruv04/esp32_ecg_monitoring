# The algorithms, explained

What the `algorithms/` package computes from the detector's beats, what each number needs before
it is shown, and how each was checked. Written 13 Nov 2026 on the `algo` branch. The companion
for the phone side is `docs/explained/app.md` (on the `app` branch). Every figure here comes from
a file in `analysis/`, named next to it.

## From beats to an NN series

The beat detector (`pan_tompkins.py`, tp2.1) gives each beat a position and a flag. A flagged
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

## The biphasic-QRS problem and a candidate fix (13 Nov, not shipped)

**The problem.** tp2.1 times a beat at the peak of its larger QRS lobe, so it must first decide
which lobe is larger. When the two lobes are close in size it refuses, flags the beat, and the
recording loses its HRV. On our own test-board recording `tb02`, 102 of 368 beats were flagged
under the phone's filter, 87 of them for this reason, leaving 62% coverage
(`analysis/tp3_own_recordings.txt`).

**The candidate, tp3** (`tp3_candidate.py`). Do not ask which lobe is the R wave. Slide the beat
against the median of the previous 16 beats and take the shift at which they match best. The
time is then referred to one peak of that median beat, which is followed from beat to beat rather
than chosen each time. Detection is untouched: the same beats, re-timed. Its settings are frozen
in `tp3_candidate.json`. `pan_tompkins.py`, `tp2_config.json` and the phone are unchanged.

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

**What it does not do.**

- It is not better everywhere. On INCART patient 24 (records I54–I56) coverage fell (90% → 48% on
  I55) and one RMSSD error grew from −0.25 to −7.55 ms. The cause was not investigated: looking
  into held-out records and then changing anything would spend the set.
- It reads RMSSD slightly low: median error −0.15 ms on MIT-BIH against −0.03 ms for tp2.1.
- It does not bring a noisy recording to 95% coverage. tb02 reaches 82%. By arithmetic that is
  about 148 s of valid time in a 3-minute session, enough for SDNN and SD2 (not yet run as a
  session); LF and HF stay withheld.
- INCART's annotations were placed by an algorithm and not corrected in position, so its RMSSD
  errors compare the two timing points; they are not absolute accuracy.

**Stopped here for review.** A port would change `BeatDetector.kt`, `pan_tompkins.py`, the parity
fixtures and `tp2_config.json`, add about 39 ms of waiting per beat, and INCART is now spent for
beat timing.

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
