# Minimum valid windows of the HRV measures

Every measure in `algorithms/` returns no value when the window holds less data than the minimum
below. The numbers live in `algorithms/config.json` (`hrv.min_window`) and are enforced by
`algorithms/core.py: gate()` and the per-measure checks; `tests/test_algorithms_*.py` test each one.

**"Valid NN time" is the summed length of the accepted NN intervals in the window**, not the clock
length of the window. A 5-minute window with half its beats rejected holds 2.5 minutes of data.

| Measure | Valid NN time | Also needs | Where the number comes from |
|---|---|---|---|
| RMSSD | 60 s | 30 accepted intervals, 5 successive differences | Ultra-short proposals of 10 s, 30 s and 60 s exist; 5 min is the convention [1]. We take 60 s. The count of 30 is the frozen tp2.1 rule (`tp2_config.json`). |
| pNN50 | 60 s | 30 intervals, 30 successive differences | "Requires a 2-min epoch", with 60 s proposed for ultra-short use [1]. We take 60 s. |
| SD1 | 60 s | as RMSSD | SD1 is RMSSD/√2 when the mean successive difference is zero [1], so it gets RMSSD's minimum. |
| SDNN | 120 s | 30 intervals | Proposals range from 60 s to 240 s; one study found 1-minute SDNN did not track the 5-minute value, another found 120 s in near-perfect agreement with 240–300 s [1]. We take 120 s. **SDNN grows with window length: compare it only with an SDNN from the same duration.** |
| SD2 | 120 s | 30 intervals, 30 successive pairs | SD2² = 2·SDNN² − SD1², so it inherits SDNN's minimum. |
| HF power | 60 s | 30 intervals, **coverage ≥ 95%**, mean NN ≤ 1250 ms | "Conventionally recorded over a minimum 1 min period" [1]. Coverage and heart-rate conditions: see below. |
| LF power, LF/HF, LFnu | 120 s | 30 intervals, **coverage ≥ 95%** (and HF's conditions for the ratios) | "Typically recorded over a minimum 2 min period" [1]. 120 s is under five cycles of 0.04 Hz, so the low edge of LF is poorly resolved at this length. |
| DFA α1 | 120 s | 200 intervals in runs of 16 or more | 120 s was the shortest epoch that estimated the 5-minute value in one study of 38 students [1]. The count comes from our simulation [2]. |
| Sample entropy | 180 s | 200 templates (3 consecutive accepted intervals each) | 180 s from the same study [1]; the count from our simulation [2]. **Its value depends on window length**, see below. |

[1] Shaffer F, Ginsberg JP. An Overview of Heart Rate Variability Metrics and Norms. *Front Public
Health* 2017;5:258 (PMC5624990). The durations are from its measure-by-measure text and its Table 4
(ultra-short-term studies: Salahuddin, Nussinovitch, Baek, Munoz, Shaffer). Read from the full text
on 11 Nov 2026. Where the studies disagree the table above says which value we took; none of these
is a consensus, and the review itself calls ultra-short-term values "controversial proxies".

[2] `analysis/hrv_min_window_simulation.txt`, written by `./hrv_min_window_sim.py`.

## What the simulation showed

**DFA α1.** On white, 1/f and random-walk series the standard deviation of α1 falls to 0.10 or less,
with bias under 0.05, from 200 intervals. That is the count enforced.

**Sample entropy.** On white noise it settles from about 200 intervals (sd 9% of the true value,
bias 1%; no undefined result from 150). On 1/f and random-walk series it never meets the rule we
set beforehand, because the value itself depends on how long the series is: the tolerance r is a
fraction of the standard deviation, and the standard deviation of a long-memory series grows with
its length. At 200 intervals SampEn of 1/f noise read 12% above its value at 4000. So the count
(200 templates) is the white-noise result, and a SampEn must only be compared with another from a
window of similar length. The pre-set rule was not met and was not changed.

**Missing beats and Lomb–Scargle.** Lomb–Scargle needs no interpolation, but holes are not free:
each missing interval spreads part of the series' variance across all frequencies, and the smaller
band is lifted most. With 2.5% of beats flagged at random (coverage 95%) HF read 7–14% high and
LF/HF 5–8% low; with 5% flagged (coverage 90%) HF read 16–30% high. LF and HF are therefore
withheld below 95% coverage. neurokit2's Lomb–Scargle has the same floor, so agreement with it does
not show the floor is absent.

## Choices that are ours, not the literature's

- **DFA box sizes 4–16 beats.** neurokit2's default is 4–11. On the MIT-BIH development records the
  two definitions differ by 0.13–0.18 at the median (`analysis/hrv_vs_neurokit_mitdb_dev.txt`).
  Before comparing α1 with a published threshold, check which range that publication used. The
  range in the original paper (Peng et al. 1995) was not checked for this document.
- **pNN50 divides by the number of successive differences.** neurokit2 divides by the number of
  intervals (differences + 1). With holes only the number of differences is well defined.
- **HF needs mean NN ≤ 1250 ms** (48 beats/min or faster). One sample per beat cannot represent
  0.4 Hz below that rate.
- **Nothing crosses a hole.** Successive differences, Poincaré pairs, DFA boxes and entropy templates
  are taken only inside runs of consecutive accepted intervals. neurokit2 joins the pieces end to end
  for DFA and SampEn, so the two differ on windows with holes by construction.

## What this means for a 2-minute session

A 120 s recording cannot hold 120 s of valid NN time: the first beat arrives after the start, the
detector's first eight beats are flagged while the polarity template fills (`POL_MIN`), and any
rejected beat costs two intervals. In a 2-minute session RMSSD, pNN50, SD1 and (at ≥ 95% coverage)
HF can be reported; SDNN, SD2, LF, LF/HF and DFA α1 cannot, and sample entropy needs over 3 minutes.
Either the session records for about 2.5 minutes, or the report leaves those out.
