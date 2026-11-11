#!/usr/bin/env python3
"""How many NN intervals do DFA alpha1 and sample entropy need?

    ./hrv_min_window_sim.py

The literature gives minimum DURATIONS for these two (docs/hrv_minimum_windows.md)
but they are computed on beats, and what limits them is the NUMBER of intervals.
This simulation measures the spread and bias of each estimator, exactly as
implemented in algorithms/hrv_nonlinear.py, on series whose true value is known:

  white   independent Gaussian intervals: alpha = 0.5,
          SampEn(m=2, r=0.2 sd) = -ln(erf(0.1)) = 2.185 in the limit
  pink    1/f noise: alpha = 1.0
  brown   random walk: alpha = 1.5

for series of N intervals, TRIALS series each. For pink and brown the reference
is the same estimator on REF_N intervals (finite box sizes 4-16 do not give the
asymptotic exponent exactly, and that is not the estimator's fault).

Rule, fixed before the run: the minimum is the smallest N at which, on all three
processes, the sd over trials is <= 0.10 for alpha1 and <= 10% of the reference
for SampEn, the bias is within half of that, and no trial is undefined.

Outcome of the first run (11 Nov 2026): alpha1 met the rule at N = 200. SampEn
did not meet it on all three processes at any N, and the per-process lines and
the note at the end of the output were added afterwards to say why. The rule
itself and the numbers were not changed.

Part 2: how much coverage do the Lomb-Scargle band powers need? Series with
known sinusoids in the VLF, LF and HF bands, 300 s; a fraction of BEATS is
flagged at random (each takes its two intervals with it); the error is against
the same series with nothing missing. Minimum coverage = the lowest tested
level at which the median error of LF, HF and LF/HF is within 15% on both
series. That threshold was chosen after seeing the table, not before.

Saves analysis/hrv_min_window_simulation.txt.
"""
import io, contextlib, math, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from algorithms import NNSeries
from algorithms.hrv_freq import band_power, BANDS
from algorithms.hrv_nonlinear import dfa_alpha1_raw, sample_entropy_raw, SCALE_MIN, SCALE_MAX, SAMPEN_M, SAMPEN_R

SEED, TRIALS, REF_N, REF_TRIALS = 20261111, 400, 4000, 40
NS = [50, 100, 150, 200, 300, 400, 600]
SD_MAX = {"alpha1": 0.10, "sampen_rel": 0.10}


def series(kind, n, rng):
    if kind == "white":
        x = rng.standard_normal(n)
    elif kind == "brown":
        x = np.cumsum(rng.standard_normal(n))
    else:                                   # pink: shape white noise by 1/sqrt(f)
        m = 2 * n
        spec = np.fft.rfft(rng.standard_normal(m))
        f = np.fft.rfftfreq(m); f[0] = f[1]
        x = np.fft.irfft(spec / np.sqrt(f), m)[:n]
    return 800.0 + 40.0 * (x - x.mean()) / x.std()


def both(x):
    a = dfa_alpha1_raw([x]) if len(x) >= SCALE_MAX else math.nan
    s, _ = sample_entropy_raw([x], float(np.std(x, ddof=1)))
    return a, s


buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"# ./hrv_min_window_sim.py   seed {SEED}, {TRIALS} trials per cell, reference {REF_TRIALS} x {REF_N} intervals")
    print(f"# DFA box sizes {SCALE_MIN}-{SCALE_MAX}; SampEn m={SAMPEN_M}, r={SAMPEN_R} sd")
    print(f"# rule: sd <= {SD_MAX['alpha1']} (alpha1), <= {100*SD_MAX['sampen_rel']:.0f}% of reference (SampEn); "
          f"|bias| within half of that; no undefined trial\n")
    rng = np.random.default_rng(SEED)
    ok = {"alpha1": {n: True for n in NS}, "sampen": {n: True for n in NS}}
    per = {}
    for kind in ("white", "pink", "brown"):
        ref = np.array([both(series(kind, REF_N, rng)) for _ in range(REF_TRIALS)])
        ra, rs = float(np.nanmean(ref[:, 0])), float(np.nanmean(ref[:, 1]))
        print(f"=== {kind}: reference alpha1 {ra:.3f}, SampEn {rs:.3f}"
              + (f" (theory {-math.log(math.erf(0.1)):.3f})" if kind == "white" else "") + " ===")
        print(f"{'N':>5} | {'alpha1 mean':>11} {'bias':>7} {'sd':>6} | {'SampEn mean':>11} {'bias %':>7} {'sd %':>6} {'undefined':>9}")
        for n in NS:
            v = np.array([both(series(kind, n, rng)) for _ in range(TRIALS)])
            a = v[:, 0]; s = v[:, 1]; und = int(np.isnan(s).sum())
            am, asd = float(np.nanmean(a)), float(np.nanstd(a, ddof=1))
            sm, ssd = float(np.nanmean(s)), float(np.nanstd(s, ddof=1))
            print(f"{n:5d} | {am:11.3f} {am-ra:+7.3f} {asd:6.3f} | {sm:11.3f} {100*(sm-rs)/rs:+7.1f} {100*ssd/rs:6.1f} {und:9d}")
            pa = asd <= SD_MAX["alpha1"] and abs(am - ra) <= SD_MAX["alpha1"] / 2
            ps = ssd / rs <= SD_MAX["sampen_rel"] and abs(sm - rs) / rs <= SD_MAX["sampen_rel"] / 2 and und == 0
            per[(kind, "alpha1", n)] = pa; per[(kind, "sampen", n)] = ps
            if not pa: ok["alpha1"][n] = False
            if not ps: ok["sampen"][n] = False
        print()

    def first(passes):
        good = [n for n in NS if all(passes[m] for m in NS if m >= n)]
        return str(good[0]) if good else "none of " + str(NS)
    for k in ("alpha1", "sampen"):
        print(f"minimum N by the rule, {k}: {first(ok[k])}   ("
              + ", ".join(f"{kind} alone: {first({n: per[(kind, k, n)] for n in NS})}"
                          for kind in ("white", "pink", "brown")) + ")")
    print("\nNote on SampEn, written after seeing the table. On white noise the estimator settles: the")
    print("rule is met from the N shown above and no trial is undefined from N = 150. On pink and brown")
    print("noise the VALUE depends on N (r is a fraction of the sd, and the sd of a long-memory series")
    print("grows with its length), so there is no N at which a short window reproduces a long one.")
    print("That is a property of sample entropy, not noise in the estimate: a SampEn is comparable only")
    print("with another from a window of similar length, as with SDNN. config.json takes the white-noise")
    print("minimum for the template count and docs/hrv_minimum_windows.md records the length dependence.")


def tone_beats(duration_s, comps, noise, rng, mean=900.0):
    t = [0.0]
    while t[-1] < duration_s:
        nn = mean + sum(a * math.sin(2 * math.pi * f * t[-1] + ph) for f, a, ph in comps)
        t.append(t[-1] + (nn + (noise * rng.standard_normal() if noise else 0.0)) / 1000.0)
    return np.array(t)


COV_TRIALS, COV_LIMIT = 200, 0.15
with contextlib.redirect_stdout(buf):
    print(f"\n\n# Part 2: Lomb-Scargle band power against missing beats; 300 s series, mean NN 900 ms, "
          f"{COV_TRIALS} trials per row, random phases")
    print("# error = (value with beats missing) / (value from the complete series) - 1, median over trials\n")
    rng = np.random.default_rng(SEED + 1)
    passed = {}
    for label, comps, noise in (
            ("LF 0.10 Hz 30 ms + HF 0.25 Hz 20 ms", [(0.10, 30.0), (0.25, 20.0)], 0.0),
            ("VLF 0.02 Hz 40 ms + LF 0.10 Hz 30 ms + HF 0.25 Hz 20 ms + 10 ms white noise",
             [(0.02, 40.0), (0.10, 30.0), (0.25, 20.0)], 10.0)):
        print(f"=== {label} ===")
        print(f"{'beats flagged':>13} {'coverage':>9} | {'LF':>7} {'HF':>7} {'LF/HF':>7} | {'worst |LF/HF|':>13}")
        for miss in (0.01, 0.025, 0.05, 0.10, 0.15):
            e = []
            for _ in range(COV_TRIALS):
                t = tone_beats(300.0, [(f, a, rng.uniform(0, 2 * math.pi)) for f, a in comps], noise, rng)
                full = NNSeries.from_times(t, clean=False)
                l0 = band_power(full.times, full.values, BANDS["lf"])
                h0 = band_power(full.times, full.values, BANDS["hf"])
                nn = NNSeries.from_times(t, flagged=rng.random(len(t)) < miss, clean=False)
                l = band_power(nn.times, nn.values, BANDS["lf"]); h = band_power(nn.times, nn.values, BANDS["hf"])
                e.append((nn.coverage, l / l0 - 1, h / h0 - 1, (l / h) / (l0 / h0) - 1))
            e = np.array(e); med = np.median(e[:, 1:], axis=0)
            print(f"{100*miss:12.1f}% {100*e[:, 0].mean():8.1f}% | {100*med[0]:+6.1f}% {100*med[1]:+6.1f}% "
                  f"{100*med[2]:+6.1f}% | {100*np.abs(e[:, 3]).max():12.0f}%")
            passed.setdefault(miss, []).append((bool(np.all(np.abs(med) <= COV_LIMIT)), float(e[:, 0].mean())))
        print()
    good = [(m, min(c for _, c in v)) for m, v in passed.items() if all(ok for ok, _ in v)]
    worst = max(good)[1] if good else None
    print(f"lowest tested coverage with every median error within {100*COV_LIMIT:.0f}% on both series: "
          + (f"{100*worst:.1f}%" if worst else "none") + "  -> config.json withholds LF and HF below 95%")
text = buf.getvalue(); print(text, end="")
out = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "analysis" / "hrv_min_window_simulation.txt"
out.write_text(text); print(f"saved {out}")
