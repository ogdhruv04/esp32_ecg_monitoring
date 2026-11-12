# The app, explained

What the Android app does, how its numbers are made, and how we know the phone computes the same
thing as the validated Python. Written 12 Nov 2026, on the `app` branch. UI rules live in
`android_app/CLAUDE.md`; this file explains the measurement side.

## What it does

The app connects to the ring over Bluetooth and does two things.

1. **Monitor.** It shows a live ECG strip on real millimetre paper. A heart rate appears only
   when signal quality is GOOD. Otherwise the screen shows "—" and a likely cause.
2. **Session.** The wearer presses Start and sits still for **3 minutes**. The app then shows a
   report: heart rate, breathing rate, and nine heart-rate-variability (HRV) measures. Every
   report is stored on the phone, and the History screen plots each measure across sessions.

Both run the same signal path. Each BLE packet carries 6 samples. Every sample goes through the
causal filter (`EcgFilter.kt`: 0.5 Hz high-pass, 50/100 Hz notch, 40 Hz low-pass) and then the
beat detector (`BeatDetector.kt`, tp2.1). The detector is a line-by-line port of `pan_tompkins.py`,
which is the version benchmarked on MIT-BIH.

## A session, step by step

1. **Start waits for a good signal.** After Start, the clock does not run until the main screen
   would show a heart rate (GOOD quality). A session therefore never opens on a signal the app
   itself would not trust.
2. **Recording.** For 180 s (`session_config.json`, `duration_s`) the session keeps every
   filtered sample and every beat the detector locates. A lost BLE packet becomes 6 lost samples:
   a hole in the signal, never a join.
3. **Tail.** The detector runs for 4 s more (`tail_s`). Search-back can find a beat up to
   1.66 RR intervals after it happened. Only beats whose position lies inside the 180 s are
   used, and only samples inside it.
4. **Report.** The session's beats become an NN series: one entry per beat-to-beat interval, with
   a hole wherever the interval can't be trusted. That is when either beat is flagged or came from
   search-back, samples were lost between the two beats, or the 20% cleaning rule rejected it
   (`pan_tompkins.clean_nn`). Every measure is computed from that series. If the stream stops and
   never returns, the session closes 15 s after its due end with what it has, and the report says
   "Ended early".

## The measures, and when each one is withheld

A measure is shown only when the session meets that measure's own minimum. Otherwise the report
shows "—" and the rule's reason, word for word from the algorithm ("102 s of valid NN intervals,
needs 120 s"). **Valid time** is the summed length of the accepted intervals, not the clock time.
**Coverage** is accepted intervals ÷ all intervals, and it is printed next to every HRV value.

| Measure | What it is | Minimum (from `algorithms/config.json`, alg1) |
|---|---|---|
| Heart rate | 60 / median of the gap-free beat-to-beat intervals | 30 intervals (`session_config.json`) |
| Breathing rate | median of the fused rates of the 32 s windows, one starting every 3 s | each window has its own gates (below); the session needs 5 windows with a rate |
| RMSSD | root mean square of successive differences | 60 s valid, 30 NN, 5 successive differences |
| SDNN | standard deviation of NN | 120 s valid, 30 NN |
| pNN50 | share of successive differences over 50 ms | 60 s valid, 30 NN, 30 differences |
| SD1, SD2 | Poincaré plot widths | SD1 as RMSSD; SD2 120 s valid, 30 pairs |
| LF, HF power | Lomb–Scargle band power, 0.04–0.15 and 0.15–0.40 Hz | LF 120 s, HF 60 s, **both 95% coverage**; HF also needs mean NN ≤ 1250 ms |
| LF/HF | LF ÷ HF | both of the above |
| DFA α1 | detrended fluctuation slope, boxes of 4–16 beats | 120 s valid, 200 NN in unbroken runs of 16 or more |

Why the minimums are what they are is in `docs/hrv_minimum_windows.md`. Two of them matter in
practice:

- **95% coverage for LF and HF.** Missing beats raise the floor of a Lomb–Scargle spectrum, and the
  smaller band rises most. At 5% of beats flagged, HF read 16–30% high in simulation
  (`analysis/hrv_min_window_simulation.txt`).
- **DFA α1 needs 200 intervals in unbroken runs.** That is more beats than a 3-minute session
  holds below about 67 bpm, so at a resting heart rate DFA α1 is usually withheld. That is
  correct, not a bug.

Sample entropy and LFnu are in `algorithms/` but not on the report. Sample entropy needs 180 s of
*valid* NN time, which a 180 s session can never hold. LFnu was not asked for.

**LF/HF carries a caveat on screen:** it is the ratio of two frequency bands, not a measure of
sympathetic–vagal balance.

**Breathing rate** uses two effects of breathing on the ECG. The heart speeds up on inspiration
(RSA), and the R-wave amplitude changes. Each gives a Lomb–Scargle spectrum over 4–40 breaths/min
in a 32 s window. A window reports a rate only when its spectrum has a clear peak and the two
methods agree, or the amplitude peak alone is strong (`algorithms/breathing.py`). On the 23
held-out BIDMC subjects, causal filter as on the phone, the fused rate was reported in 41% of
windows (1282 of 3141), with pooled MAE 0.50 breaths/min. Per subject, the median MAE was 0.43
and the median coverage 16% (`analysis/breathing_bidmc_heldout.txt`). So in most windows it
reports nothing, but when it does report, it is close. The session-level rule (median of the
windows, at least 5) is the app's own choice. It was not tuned or validated.

### Not on the report yet

The report model and the database already hold four **hidden slots**: rhythm check, ectopic count,
motion and arousal vs the wearer's baseline (`PendingSlots` in `SessionStore.kt`). They are
always empty and never drawn (`PENDING_SLOTS_VISIBLE = false` in `SessionUi.kt`). Each appears once
a validated algorithm feeds it (`docs/MIDTERM_PLAN.md`, weeks 2–3).

## How we know the phone computes the same numbers

Every measure is ported from `algorithms/` to Kotlin (`android_app/.../algorithms/`). The Python
is the reference, because it is the version validated against neurokit2 on MIT-BIH and against
annotated breaths on BIDMC. Kotlin tests pin the port to it:

| Test | What it requires |
|---|---|
| `HrvParityTest` | on NN series from 6 real recordings (two of them with an injected artifact or a sign flip), plus 1 that passes every gate: each measure's value to 1e-9, its withheld reason word for word, its counts, valid time and coverage. Also the ungated arithmetic of every measure, so a measure that is (rightly) withheld on short data is still checked number for number |
| `SessionParityTest` | 5 real recordings fed sample by sample through `BeatDetector` + `SessionRecorder`: every report measure, and the fused breathing rate of every 32 s window, against `session_reference.py`. This is the breathing port's parity test too |
| `SessionPipelineTest` | a session recorded through `EcgPipeline` (packets, seq gaps) equals one fed directly |
| `AlgorithmsConfigTest` | every ported constant equals `algorithms/config.json` and `session_config.json` |
| `SessionStoreTest` | a report survives Room unchanged |

The fixtures come from `./make_session_fixtures.py`, which also saves the Python reference reports
in `analysis/app_session_reference.txt`. If anything in `algorithms/` changes, re-run it and the
tests show where the port no longer matches.

Withheld reasons format numbers the way Python does (exact binary value, round half to even, never
the device locale). Without that, a reason could read "60 s" on one side and "61 s" on the other.

## What our own data says so far

Only two of our captures are longer than a session: the test-board recordings of 27 Oct 2026. On
each, a 3-minute session starting 20 s in (`analysis/app_session_reference.txt`, Python reference):

- `tb02`: heart rate 77.0 bpm; RMSSD 36.3 ms, pNN50 16.4%, SD1 25.8 ms at **62% NN coverage**
  (104.8 s valid); breathing 19.8 breaths/min from 5 of 50 windows. SDNN, SD2, LF and DFA α1 are
  withheld (under 120 s valid), and HF too (coverage under 95%).
- `tb01`: heart rate 98.4 bpm; RMSSD 18.1 ms at 62% coverage; no breathing window gave a rate.

The low coverage is the open biphasic-QRS issue in the root `CLAUDE.md`: the detector cannot
decide the beat's polarity, so it flags the beat. On the phone this shows up as a report with many
"—". **No session of ours has yet populated the whole report.** The fully populated layout was
only seen on MIT-BIH development record 103 (below).

The same sessions replayed in the app give slightly different numbers from the reference above.
Two reasons. Replay loses a whole 6-sample packet wherever the capture misses one sample, as BLE
would. And the app's filter is `EcgFilter.kt`, which the fixtures approximate in scipy. The parity
tests take both out by feeding the same filtered samples to both sides.

## Replay, screenshots and public data

Debug builds bundle real captures for replay: `dual03_*`, `dual02_ring`, `dual01_ring`, and now
`tb01` and `tb02`, the only ones long enough for a session. `./make_public_replay.py` converts one
**development** MIT-BIH record into the same CSV format, scaled to codes by the nominal
2621.44 codes/mV. It writes into the gitignored `android_app/replay_public/`, because datasets are
never committed. Debug builds bundle it when it is there. MIT-BIH is ODC-By 1.0: cite it and
PhysioNet wherever an image made from it is shown.

`SessionScreenshots` renders every session state from those replays, portrait and landscape, with
the report also at 1.3× and 2× system font. The renders go to
`android_app/screenshots/after/session_*.png`. The `report_mitdb103` and populated-history renders
need the public replay; without it those tests are skipped.

## Storage

Room database `sessions.db` on the phone only, with two tables:

- `sessions`: one row per session. Start time, length, replay file (null when live), beats, lost
  samples, share of GOOD quality, the versions line (`session ses1 · algorithms alg1 · detector
  tp2.1`) and the four pending slots.
- `measures`: one row per measure. Value or null, unit, withheld reason, count used, valid time,
  coverage, and the breathing range.

The schema is exported to `android_app/app/schemas/` so a later migration can be tested. History
draws one point per session, never joined: filled dots for live sessions, squares for replays, a
tick under the axis where the measure was withheld, and a dashed line at the median of the
sessions shown. That median is the only "baseline" for now. The arousal-vs-baseline work is a
later item.

## Limits

- Nothing here is validated **on the ring**. The methods are validated on public data. The phone
  is shown to compute what the Python computes, which is a different claim.
- SDNN grows with recording length: compare only sessions of the same length. All sessions are
  180 s.
- The breathing session rule (5 windows) and the heart-rate session rule (30 intervals) are our
  own, untuned choices.
- `tb01`/`tb02` were recorded on the test board, not the ring, and whether a person was wired
  exactly as in the bench protocol is not recorded in their logs.
