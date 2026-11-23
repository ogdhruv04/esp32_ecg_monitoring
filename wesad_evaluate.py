#!/usr/bin/env python3
"""WESAD pilot report (docs/wesad_plan.md, section 10).

    ./wesad_evaluate.py --pilot --features <main>/data/wesad_features --subjects S2 S3

Reports, from the feature tables wesad_features.py wrote: durations and label
runs; how often each feature is reported, by part; each subject's reference
mean and sd; the median z-score of each feature by part (a check on signs and
units, not a result); A1 (wrist pulses against chest ECG beats) and A2 (the
apparent beat-to-pulse delay along the recording); run time and peak memory.

It computes NO classification metric. The full evaluation (plan sections 6-7)
is not written yet, and this script refuses to run without --pilot.
Saves analysis/wesad_pilot.txt.
"""
import argparse, io, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--pilot", action="store_true")
ap.add_argument("--features", required=True)
ap.add_argument("--subjects", nargs="+", required=True)
args = ap.parse_args()
if not args.pilot:
    sys.exit("refusing: only the pilot report exists; the full evaluation (plan sections 6-7) is not written yet")

from algorithms import arousal
from algorithms.core import CONFIG

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
PARTS = ["reference", "baseline", "stress", "amusement", "meditation_1", "meditation_2"]
BLOCKS = ["ecg_full", "bvp", "eda_wrist", "eda_chest", "temp_wrist", "temp_chest"]
COLS = [c for b in BLOCKS for c in arousal.columns(b)] + ["eda_wrist.scr_rate_05"]
out = io.StringIO()
p = lambda *a: print(*a, file=out)

T = {s: pd.read_csv(os.path.join(args.features, f"{s}.csv")) for s in args.subjects}
META = {s: json.load(open(os.path.join(args.features, f"{s}.json"))) for s in args.subjects}
commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

p("WESAD pilot (docs/wesad_plan.md section 10). PILOT ONLY: no classification metric is computed.")
p(f"subjects {' '.join(args.subjects)}; code {commit}; config {CONFIG['version']}, wesad block frozen {CONFIG['wesad']['frozen']}")
p("Data: WESAD (Schmidt et al., ICMI 2018). Development data for these algorithms; the subjects stay in the full run.")
p("Windows 180 s every 30 s; ECG causal monitoring filter, 50 Hz notch, tp3 detector at 256 Hz.\n")

p("== 1. Recordings")
for s, m in META.items():
    d = m["durations_s"]
    p(f"{s}: order {m['order']}; durations s: " + ", ".join(f"{k} {v:.1f}" for k, v in d.items()))
    p(f"    parts s: " + ", ".join(f"{k} {a:.0f}-{b:.0f} ({b - a:.0f})" for k, (a, b) in m["parts"].items()))
    codes = {}
    for c, a, b in m["runs"]:
        codes.setdefault(c, []).append(b - a)
    p("    label runs: " + "; ".join(f"label {c}: {len(v)} run(s), {sum(v):.0f} s" for c, v in sorted(codes.items())))
    p(f"    windows {m['windows']}, ECG beats {m['beats']} ({m['beats_flagged']} flagged, "
      f"{100 * m['beats_flagged'] / max(1, m['beats']):.1f}%), pulses {m['pulses']}; "
      f"min EDA wrist {m['eda_wrist_min_us']:.3f} uS, chest {m['eda_chest_min_us']:.3f} uS")
    p(f"    run time {m['total_s']} s (ECG detector {m['ecg_s']} s), peak memory {m['peak_rss_mb']} MB")

p("\n== 2. Windows per part, and share in which each feature was reported (%)")
for s, t in T.items():
    n = t["part"].value_counts()
    p(f"{s}: windows " + ", ".join(f"{k} {n.get(k, 0)}" for k in PARTS))
    p(f"  {'feature':28s}" + "".join(f"{k[:10]:>11s}" for k in PARTS))
    for c in COLS:
        row = [100 * t.loc[t["part"] == k, c].notna().mean() if n.get(k, 0) else np.nan for k in PARTS]
        p(f"  {c:28s}" + "".join(f"{v:11.0f}" for v in row))
low = [(s, c) for s, t in T.items() for c in COLS
       for k in ("baseline", "stress") if t.loc[t["part"] == k, c].notna().mean() < 0.5]
p("Reported in under half of the baseline or stress windows (plan section 10, rule 3): "
  + (", ".join(sorted({f"{c} ({s})" for s, c in low})) or "none"))

p("\n== 3. Reference segment: mean and sd (n-1) per subject; NaN = fewer than "
  f"{CONFIG['arousal']['min_reference_windows']} reference windows reported it")
stats = {s: arousal.reference_stats(t, COLS) for s, t in T.items()}
p(f"  {'feature':28s}" + "".join(f"{s + ' mean':>12s}{s + ' sd':>10s}" for s in T))
for c in COLS:
    p(f"  {c:28s}" + "".join(f"{stats[s][0][c]:12.4g}{stats[s][1][c]:10.3g}" for s in T))

p("\n== 4. Median z-score by part (sd floor = half the median reference sd over THESE pilot subjects;")
p("   in the full run it comes from the training subjects of each fold). Signs and units only; not a result.")
floor = arousal.sd_floor([stats[s][1] for s in T])
for s, t in T.items():
    z = arousal.zscore(t, COLS, *stats[s], floor)
    p(f"{s}:  {'feature':28s}" + "".join(f"{k[:10]:>11s}" for k in PARTS))
    for c in COLS:
        p(f"     {c:28s}" + "".join(f"{z.loc[z['part'] == k, c].median():11.2f}" for k in PARTS))

p("\n== 5. A1: wrist pulses against chest ECG beats, per part (windows overlap; descriptive)")
p("   Matching: pulses shifted back by the window's median beat-to-pulse delay, +-150 ms, one to one.")
p("   Se = matched / ECG beats, P+ = matched / pulses; counted once per window, so overlapping windows repeat beats.")
for s, t in T.items():
    p(f"{s}:")
    for k in PARTS:
        g = t[t["part"] == k]
        if not len(g):
            continue
        se = g["match.tp"].sum() / max(1, g["match.beats"].sum())
        pp = g["match.tp"].sum() / max(1, g["match.pulses"].sum())
        both = g[["ecg.hr", "bvp.pr"]].dropna()
        dhr = both["bvp.pr"] - both["ecg.hr"]
        rr = g[["ecg.ln_rmssd", "bvp.ln_rmssd_p"]].dropna()
        drm = np.exp(rr["bvp.ln_rmssd_p"]) - np.exp(rr["ecg.ln_rmssd"])
        p(f"  {k:13s} Se {100 * se:5.1f}%  P+ {100 * pp:5.1f}%  | rate (pulse - ECG) over {len(both)}/{len(g)} windows: "
          + (f"bias {dhr.mean():+.2f}/min, LoA {dhr.mean() - 1.96 * dhr.std():+.2f}..{dhr.mean() + 1.96 * dhr.std():+.2f}"
             if len(both) > 1 else "n/a")
          + f" | RMSSD pulse vs ECG over {len(rr)}/{len(g)} windows: "
          + (f"median {np.median(np.exp(rr['bvp.ln_rmssd_p'])):.1f} vs {np.median(np.exp(rr['ecg.ln_rmssd'])):.1f} ms, "
             f"median difference {np.median(drm):+.1f} ms" if len(rr) else "n/a")
          + f" | coverage median ECG {100 * g['ecg_info.coverage'].median():.0f}%, pulse {100 * g['bvp_info.coverage'].median():.0f}%")

p("\n== 6. A2: apparent ECG-beat-to-wrist-pulse delay along the recording (NOT pulse arrival time;")
p("   the devices were aligned by hand from a double-tap). Per part: median of the windows' medians, ms.")
for s, t in T.items():
    g = t.dropna(subset=["sync.delay_ms"])
    by = g.groupby("part").agg(t0=("t0", "min"), delay=("sync.delay_ms", "median"), iqr=("sync.delay_iqr_ms", "median"))
    by = by.sort_values("t0")
    p(f"{s}: " + "; ".join(f"{k} (from {r.t0:.0f} s) {r.delay:.0f} ms, IQR within windows {r.iqr:.0f}" for k, r in by.iterrows()))
    if len(g) > 2:
        mid = (g["t0"] + g["t1"]) / 2 / 3600.0
        slope = np.polyfit(mid, g["sync.delay_ms"], 1)[0]
        p(f"    least-squares slope over all windows: {slope:+.1f} ms per hour ({len(g)} windows; posture and heart rate also move this delay)")

text = out.getvalue()
print(text)
dest = HERE / "analysis" / "wesad_pilot.txt"
dest.write_text(text)
print(f"saved {dest}")
