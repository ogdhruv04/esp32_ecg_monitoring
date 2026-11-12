# The app, explained

What the Android app does, how its numbers are made, and how we know the phone computes the same
thing as the validated Python. Written 12 Nov 2026 on the `app` branch, revised the same day after
review. UI rules live in `android_app/CLAUDE.md`; this file explains the measurement side.

## What it does

The app connects to the ring over Bluetooth and does two things.

1. **Monitor.** It shows a live ECG strip on real millimetre paper. A heart rate appears only
   when signal quality is GOOD. Otherwise the screen shows "—" and a likely cause.
2. **Session.** The wearer picks a **standard (3-minute)** or **extended (5-minute)** session,
   presses Start and sits still. The app then shows a report. Every report is stored on the
   phone, and the History screen plots each measure across sessions, by date.

Both run the same signal path. Each BLE packet carries 6 samples. Every sample goes through the
causal filter (`EcgFilter.kt`: 0.5 Hz high-pass, 50/100 Hz notch, 40 Hz low-pass) and then the
beat detector (`BeatDetector.kt`, tp2.1). The detector is a line-by-line port of `pan_tompkins.py`,
which is the version benchmarked on MIT-BIH.

## A session, step by step

1. **Start waits for a good signal.** After Start, the clock does not run until the main screen
   would show a heart rate (GOOD quality). A session therefore never opens on a signal the app
   itself would not trust.
2. **Recording.** For the session's length (`session_config.json`, `kinds`: 180 s or 300 s), the
   session keeps every filtered sample and every beat the detector locates. A lost BLE packet
   becomes 6 lost samples: a hole in the signal, never a join.
3. **Tail.** The detector runs for 4 s more (`tail_s`). Search-back can find a beat up to
   1.66 RR intervals after it happened. Only beats whose position lies inside the session are
   used, and only samples inside it.
4. **Report.** The session's beats become an NN series: one entry per beat-to-beat interval, with
   a hole wherever the interval can't be trusted. That is when either beat is flagged or came from
   search-back, samples were lost between the two beats, or the 20% cleaning rule rejected it
   (`pan_tompkins.clean_nn`). Every measure is computed from that series. If the stream stops and
   never returns, the session closes 15 s after its due end with what it has, and the report says
   "Ended early".

## The report

It has two layers.

- **Summary**: heart rate, RMSSD and breathing rate. Each comes with a "usual" line once the
  wearer has **3 or more earlier live sessions**: the median and the range of that measure over
  those sessions, and how many had a value. Until then the summary says "Building your baseline:
  N of 3 sessions". Replays never count, and neither does the session being shown.
- **All measures**: collapsed by default. It holds every other measure with the same subtitles:
  the count and coverage when a value is shown, the withheld reason otherwise. On a standard
  report, a closing line says that DFA α1 and sample entropy are in the extended session.

Tapping any measure, in either layer, opens one line on what it reflects and its main limit. The
wording is below.

### What each measure means (shown on tap) — for review

The app shows exactly these lines (`EXPLANATIONS` in `SessionUi.kt`). `ExplanationsTest` fails
if the app's wording and this list differ, so a change made here is not live until the code
matches it.

| Measure | Line shown on tap |
|---|---|
| Heart rate | How fast your heart beat over the session. Posture, movement and caffeine move it as much as rest does. |
| RMSSD | Beat-to-beat variation, mostly from the vagus nerve's rest-and-digest braking. Breathing changes it, so compare sessions done the same way. |
| Breathing rate | Breaths per minute, read from how breathing sways the heartbeat and the ECG's height. Often withheld, because many stretches don't show breathing clearly. |
| SDNN | Overall spread of the beat intervals. It grows with recording length, so compare only sessions of the same length. |
| pNN50 | Share of neighbouring beat intervals that differ by more than 50 ms. A coarse cousin of RMSSD; near 0% it cannot tell low values apart. |
| SD1 | Short-term variability from the Poincaré plot. It is RMSSD in another form, so it adds little on its own. |
| SD2 | Longer-term variability from the Poincaré plot. Like SDNN, it depends on recording length. |
| LF power | Power of slow heart-rate swings (0.04–0.15 Hz). It mixes several influences, including slow breathing, and is noisy over a few minutes. |
| HF power | Power of heart-rate swings at normal breathing speed, linked to vagal activity. Breathing slower than 9 a minute moves this out of the band. |
| LF/HF | Ratio of the two bands. It is not a measure of stress or of sympathetic–vagal balance. |
| DFA α1 | How strongly beat intervals are correlated over 4 to 16 beats. The value depends on that range, so compare only with figures that use it. |
| Sample entropy | How unpredictable the beat-interval pattern is. The value depends on series length, so compare only sessions of the same length. |

"9 a minute" is the bottom of the HF band: 0.15 Hz × 60.

## The measures, and when each one is withheld

A measure is shown only when the session meets that measure's own minimum. Otherwise the report
shows "—" and the rule's reason, word for word from the algorithm ("102 s of valid NN intervals,
needs 120 s"). **Valid time** is the summed length of the accepted intervals, not the clock time.
**Coverage** is accepted intervals ÷ all intervals, and it is printed next to every HRV value.

| Measure | On | What it is | Minimum (from `algorithms/config.json`, alg1) |
|---|---|---|---|
| Heart rate | both | 60 / median of the gap-free beat-to-beat intervals | 30 intervals (provisional, see below) |
| Breathing rate | both | median of the fused rates of the 32 s windows, one starting every 3 s (`bidmc.step_s`) | each window has its own gates; the session needs 5 windows with a rate, spanning no more than 4 breaths/min (provisional) |
| RMSSD | both | root mean square of successive differences | 60 s valid, 30 NN, 5 successive differences |
| SDNN | both | standard deviation of NN | 120 s valid, 30 NN |
| pNN50 | both | share of successive differences over 50 ms | 60 s valid, 30 NN, 30 differences |
| SD1, SD2 | both | Poincaré plot widths | SD1 as RMSSD; SD2 120 s valid, 30 pairs |
| LF, HF power | both | Lomb–Scargle band power, 0.04–0.15 and 0.15–0.40 Hz | LF 120 s, HF 60 s, **both 95% coverage**; HF also needs mean NN ≤ 1250 ms |
| LF/HF | both | LF ÷ HF | both of the above |
| DFA α1 | extended | detrended fluctuation slope, boxes of 4–16 beats | 120 s valid, 200 NN in unbroken runs of 16 or more |
| Sample entropy | extended | m = 2, r = 0.2 × SD | 180 s valid, 200 templates of 3 consecutive intervals |

Why the HRV minimums are what they are is in `docs/hrv_minimum_windows.md`. Three matter in
practice:

- **95% coverage for LF and HF.** Missing beats raise the floor of a Lomb–Scargle spectrum, and the
  smaller band rises most. At 5% of beats flagged, HF read 16–30% high in simulation
  (`analysis/hrv_min_window_simulation.txt`).
- **DFA α1 and sample entropy need the extended session.** DFA α1 needs 200 intervals in
  unbroken runs, which is more beats than 3 minutes hold below about 67 bpm. Sample entropy needs
  180 s of *valid* time, which a 180 s session can never hold. So the standard report leaves
  both out rather than always showing "—".
- **Sample entropy and SDNN depend on recording length.** Compare only sessions of the same kind.

**LF/HF carries a caveat on screen:** it is the ratio of two frequency bands, not a measure of
sympathetic–vagal balance.

### Session-level rules: provisional

Three rules belong to the session, not to any one measure:
- the minimum number of intervals for a heart rate,
- the minimum number of breathing windows,
- how far apart the window rates may be.

They belong in `algorithms/config.json`, in a `session` block that the algorithms workstream has
not written yet. Until it does, the app uses provisional values: 30 intervals, 5 windows, and a
spread of at most 4 breaths/min. They are set by hand and untuned (`session_reference.PROVISIONAL`,
`SessionRules` in `Session.kt`). Every reason they produce ends "(provisional rule)", and the
breathing subtitle says "provisional rules". `AlgorithmsConfigTest` fails as soon as
`config.json` gains a `session` block, so the two cannot quietly disagree.

The spread rule exists because the windows of one session can lock onto different rhythms. On
`tb02`, the 5 windows with a rate span 6.0–19.9 breaths/min (`analysis/app_session_reference.txt`).
That is not one breathing rate, and the median of such windows would be a number that means
nothing. The breathing rate is now withheld there.

**Breathing rate** uses two effects of breathing on the ECG. The heart speeds up on inspiration
(RSA), and the R-wave amplitude changes. Each gives a Lomb–Scargle spectrum over 4–40 breaths/min
in a 32 s window. A window reports a rate only when its spectrum has a clear peak and the two
methods agree, or the amplitude peak alone is strong (`algorithms/breathing.py`). On the 23
held-out BIDMC subjects, causal filter as on the phone, the fused rate was reported in 41% of
windows (1282 of 3141), with pooled MAE 0.50 breaths/min. Per subject, the median MAE was 0.43
and the median coverage 16% (`analysis/breathing_bidmc_heldout.txt`). So in most windows it
reports nothing, but when it does report, it is close. The session-level rules above are not
part of that validation.

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
| `HrvParityTest` | on NN series from 6 real recordings (two of them with an injected artifact or a sign flip), plus 1 that passes every gate: each measure's value to 1e-9, its withheld reason word for word, its counts, valid time and coverage. Also the ungated arithmetic of every measure, sample entropy included, so a measure that is (rightly) withheld on short data is still checked number for number |
| `SessionParityTest` | 6 sessions on real recordings (one of them extended) fed sample by sample through `BeatDetector` + `SessionRecorder`: every report measure, and the fused breathing rate of every 32 s window, against `session_reference.py`. This is the breathing port's parity test too |
| `SessionPipelineTest` | a session recorded through `EcgPipeline` (packets, seq gaps) equals one fed directly |
| `AlgorithmsConfigTest` | every ported constant equals `algorithms/config.json` and `session_config.json`; the session rules stay labelled provisional until `config.json` has them |
| `BaselineTest` | "usual" uses earlier live sessions only, needs 3, skips withheld values |
| `ExplanationsTest` | the tap explanations are this document's wording |
| `SessionStoreTest`, `SessionMigrationTest` | a report survives Room unchanged; a schema-1 database migrates with its sessions kept |

The fixtures come from `./make_session_fixtures.py`, which also saves the Python reference reports
in `analysis/app_session_reference.txt`. If anything in `algorithms/` changes, re-run it and the
tests show where the port no longer matches.

Withheld reasons format numbers the way Python does (exact binary value, round half to even, never
the device locale). Without that, a reason could read "60 s" on one side and "61 s" on the other.

## What our own data says so far

Only two of our captures are longer than a standard session: the test-board recordings of
27 Oct 2026. None is long enough for an extended one. For a 3-minute session starting 20 s in
(`analysis/app_session_reference.txt`, Python reference):

- `tb02`: heart rate 77.0 bpm; RMSSD 36.3 ms, pNN50 16.4%, SD1 25.8 ms at **62% NN coverage**
  (104.8 s valid). Breathing is withheld by the spread rule. SDNN, SD2 and LF are withheld (under
  120 s valid), and HF too (coverage under 95%).
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

Debug builds bundle real captures for replay: `dual03_*`, `dual02_ring`, `dual01_ring`, `tb01`
and `tb02`. `./make_public_replay.py` converts one **development** MIT-BIH record into the same CSV
format, scaled to codes by the nominal 2621.44 codes/mV. It writes into the gitignored
`android_app/replay_public/`, because datasets are never committed. Debug builds bundle it when it
is there. MIT-BIH is ODC-By 1.0: cite it and PhysioNet wherever an image made from it is shown.

`SessionScreenshots` renders every session state from those replays, portrait and landscape, with
the report also at 1.3× and 2× system font. The renders go to
`android_app/screenshots/after/session_*.png`. One render, `report_mitdb103_baseline`, shows the
"usual" lines using other replayed sessions of record 103 as the earlier sessions. That is only so
the state can be seen: on the phone a replay never counts. The MIT-BIH renders need the public
replay; without it those tests are skipped.

## Storage

Room database `sessions.db` on the phone only, schema version 2, with two tables:

- `sessions`: one row per session. Kind, start time, length, replay file (null when live), beats,
  lost samples, share of GOOD quality, the versions line (`session ses2 · algorithms alg1 ·
  detector tp2.1`) and the four pending slots.
- `measures`: one row per measure. Value or null, unit, withheld reason, count used, valid time,
  coverage, and the breathing range.

Schemas are exported to `android_app/app/schemas/`. Migration 1 → 2 adds the kind, and existing
sessions become standard.

History plots one point per session against its **date** (days apart sit days apart), never
joined:
- filled dots for live sessions, squares for replays,
- a tick under the axis where the measure was withheld,
- a dashed line at the median of the sessions shown.

The first and last dates are always labelled, and others where they fit. DFA α1 and sample
entropy plot extended sessions only.

## Limits

- Nothing here is validated **on the ring**. The methods are validated on public data. The phone
  is shown to compute what the Python computes, which is a different claim.
- SDNN, SD2 and sample entropy depend on recording length: compare only sessions of the same kind.
- The session-level rules are provisional and untuned.
- The "usual" is the median and range of a handful of sessions. It shows where a value sits
  among the wearer's own; it is not a reference range and not an arousal index.
- `tb01`/`tb02` were recorded on the test board, not the ring, and whether a person was wired
  exactly as in the bench protocol is not recorded in their logs.
