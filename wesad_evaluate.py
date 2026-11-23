#!/usr/bin/env python3
"""WESAD evaluation (docs/wesad_plan.md, sections 6-8 and 10).

    ./wesad_evaluate.py --features <main>/data/wesad_features              # full run, all 15 subjects
    ./wesad_evaluate.py --pilot --features <main>/data/wesad_features --subjects S2 S3

Full run (sections 6-8, with the 23 Nov rule-3 amendments, `arousal.models` in
algorithms/config.json): leave-one-subject-out logistic regression of the
second half of the baseline against stress; the six primary models, the
per-modality ablation (each modality alone; All four and Wrist-only with each
modality removed), each on its own windows and on the windows every compared
model classified; B1 (false alarms on amusement and meditation, by condition
order); B2 (stress against baseline + amusement, the task of Schmidt et al.
2018, with the comparison of section 8); B3 (ECG-full); B4 (chest EDA and
TEMP); B5 (skin responses at 0.05 uS); A1 and A2 over all subjects.
Reported for the stress class: Se, Sp, P+, balanced accuracy, AUC, accuracy and
class-averaged F1, always with the rejection rate of each class; pooled over
windows with a 95% bootstrap interval over subjects, and per subject as median
and range. It refuses to compute any classification metric on fewer than all
15 subjects. Saves analysis/wesad_evaluation.txt (--out to save elsewhere).

Pilot (section 10): durations and label runs, feature availability, reference
statistics, median z-scores (signs and units), A1 and A2. No classification
metric. Saves analysis/wesad_pilot.txt.
"""
import argparse, io, json, os, pathlib, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--pilot", action="store_true")
ap.add_argument("--features", required=True)
ap.add_argument("--subjects", nargs="+", help="pilot: the subjects; full run: must be all 15 (the default)")
ap.add_argument("--out", help="report path (default analysis/wesad_evaluation.txt or analysis/wesad_pilot.txt)")
args = ap.parse_args()

from algorithms import arousal
from algorithms.core import CONFIG

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
A = CONFIG["arousal"]
ALL = CONFIG["wesad"]["subjects"]
PARTS = ["reference", "baseline", "stress", "amusement", "meditation_1", "meditation_2"]
BLOCKS = ["ecg_full", "bvp", "eda_wrist", "eda_chest", "temp_wrist", "temp_chest"]
COLS = [c for b in BLOCKS for c in arousal.columns(b)] + ["eda_wrist.scr_rate_05"]
out = io.StringIO()
p = lambda *a, **k: print(*a, file=out, **k)

subjects = args.subjects or ALL
if not args.pilot and sorted(subjects) != sorted(ALL):
    sys.exit(f"refusing: the full evaluation needs all {len(ALL)} subjects (plan section 10); got {len(subjects)}")
missing = [s for s in subjects if not os.path.exists(os.path.join(args.features, f"{s}.csv"))]
if missing:
    sys.exit(f"no feature table for {' '.join(missing)}: run wesad_features.py first")
T = {s: pd.read_csv(os.path.join(args.features, f"{s}.csv")) for s in subjects}
META = {s: json.load(open(os.path.join(args.features, f"{s}.json"))) for s in subjects}
commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "--", "algorithms", "wesad_evaluate.py",
                        "wesad_features.py"], capture_output=True, text=True).stdout.strip()
code = commit + (" (+ uncommitted changes)" if dirty else "")


def recordings_section():
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


def a1_line(g):
    se = g["match.tp"].sum() / max(1, g["match.beats"].sum())
    pp = g["match.tp"].sum() / max(1, g["match.pulses"].sum())
    both = g[["ecg.hr", "bvp.pr"]].dropna()
    dhr = both["bvp.pr"] - both["ecg.hr"]
    rr = g[["ecg.ln_rmssd", "bvp.ln_rmssd_p"]].dropna()
    drm = np.exp(rr["bvp.ln_rmssd_p"]) - np.exp(rr["ecg.ln_rmssd"])
    return (f"Se {100 * se:5.1f}%  P+ {100 * pp:5.1f}%  | rate (pulse - ECG) over {len(both)}/{len(g)} windows: "
            + (f"bias {dhr.mean():+.2f}/min, LoA {dhr.mean() - 1.96 * dhr.std():+.2f}..{dhr.mean() + 1.96 * dhr.std():+.2f}"
               if len(both) > 1 else "n/a")
            + f" | RMSSD pulse vs ECG over {len(rr)}/{len(g)} windows: "
            + (f"median {np.median(np.exp(rr['bvp.ln_rmssd_p'])):.1f} vs {np.median(np.exp(rr['ecg.ln_rmssd'])):.1f} ms, "
               f"median difference {np.median(drm):+.1f} ms" if len(rr) else "n/a")
            + f" | coverage median ECG {100 * g['ecg_info.coverage'].median():.0f}%, pulse {100 * g['bvp_info.coverage'].median():.0f}%")


A1_HEAD = ("   Matching: pulses shifted back by the window's median beat-to-pulse delay, +-150 ms, one to one.",
           "   Se = matched / ECG beats, P+ = matched / pulses; counted once per window, so overlapping windows repeat beats.")


def a2_section(title):
    p(title)
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


# ===================================================================== pilot
def pilot():
    p("WESAD pilot (docs/wesad_plan.md section 10). PILOT ONLY: no classification metric is computed.")
    p(f"subjects {' '.join(subjects)}; code {code}; config {CONFIG['version']}, wesad block frozen {CONFIG['wesad']['frozen']}")
    p("Data: WESAD (Schmidt et al., ICMI 2018). Development data for these algorithms; the subjects stay in the full run.")
    p("Windows 180 s every 30 s; ECG causal monitoring filter, 50 Hz notch, tp3 detector at 256 Hz.\n")
    recordings_section()

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
      f"{A['min_reference_windows']} reference windows reported it")
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
    p(*A1_HEAD, sep="\n")
    for s, t in T.items():
        p(f"{s}:")
        for k in PARTS:
            g = t[t["part"] == k]
            if len(g):
                p(f"  {k:13s} " + a1_line(g))
    a2_section("\n== 6. A2: apparent ECG-beat-to-wrist-pulse delay along the recording (NOT pulse arrival time;")
    return "wesad_pilot.txt"


# ================================================================ full run
POS, NEG = ("stress",), ("baseline",)
NEG_B2 = ("baseline", "amusement")
CACHE = {}


def run(name, blocks=None, cols=None, negative=NEG):
    """LOSO (rows, folds, cols) of one model, cached by name and task."""
    key = (name, negative)
    if key not in CACHE:
        cols = arousal.model_columns(blocks) if cols is None else list(cols)
        rows, folds = arousal.loso(T, cols, positive=POS, negative=negative)
        CACHE[key] = (rows, folds, cols)
    return CACHE[key]


pct = lambda x: f"{100 * x:5.1f}" if np.isfinite(x) else "  n/a"
ci = lambda lo_hi: f"[{100 * lo_hi[0]:4.1f}-{100 * lo_hi[1]:5.1f}]" if np.all(np.isfinite(lo_hi)) else "[    n/a   ]"
BOOT_KEYS = ("se", "sp", "balanced_accuracy", "auc", "accuracy", "f1_macro")


def pooled_header():
    p(f"  {'model':30s} {'Se':>18s} {'Sp':>18s} {'P+':>5s} {'bal.acc':>18s} {'AUC':>18s} {'acc':>18s} {'F1':>18s}"
      f" | rej: {'stress':>6s} {'neg':>6s} | n: {'stress':>6s} {'neg':>5s}")


def pooled_line(name, rows, negative=NEG, boot=True):
    s = arousal.scores(rows, positive=POS, negative=negative)
    b = arousal.bootstrap(rows, keys=BOOT_KEYS, positive=POS, negative=negative) if boot else None
    f = lambda k: f"{pct(s[k])} {ci(b[k])}" if boot else f"{pct(s[k]):>18s}"
    p(f"  {name:30s} {f('se')} {f('sp')} {pct(s['ppv'])} {f('balanced_accuracy')} {f('auc')} {f('accuracy')} {f('f1_macro')}"
      f" |      {pct(s['rejected_positive']):>6s} {pct(s['rejected_negative']):>6s} |    {s['n_positive']:6d} {s['n_negative']:5d}")
    return s


def spread_line(name, rows, negative=NEG):
    ps = arousal.per_subject(rows, positive=POS, negative=negative)
    def mr(k):
        v = ps[k].dropna().astype(float)
        return f"{100 * v.median():5.1f} [{100 * v.min():5.1f}, {100 * v.max():5.1f}] n={len(v):2d}" if len(v) else "n/a"
    p(f"  {name:30s} Se {mr('se')} | Sp {mr('sp')} | bal.acc {mr('balanced_accuracy')} | acc {mr('accuracy')}"
      f" | F1 {mr('f1_macro')} | AUC {mr('auc')}")
    return ps


def availability_section():
    p("== 2. Feature availability over all 15 subjects: share of windows in which each feature was reported (%)")
    allt = pd.concat([t.assign(subject=s) for s, t in T.items()])
    n = allt["part"].value_counts()
    p(f"  windows: " + ", ".join(f"{k} {n.get(k, 0)}" for k in PARTS))
    p(f"  {'feature':28s}" + "".join(f"{k[:10]:>11s}" for k in PARTS) + "   subjects under 50% in baseline or stress")
    for c in COLS:
        row = [100 * allt.loc[allt["part"] == k, c].notna().mean() for k in PARTS]
        low = [s for s, t in T.items() if min(t.loc[t["part"] == k, c].notna().mean() for k in ("baseline", "stress")) < 0.5]
        p(f"  {c:28s}" + "".join(f"{v:11.0f}" for v in row) + f"   {len(low):2d} {' '.join(low)}")
    p("  (For the record. Rule 3 was applied from the pilot alone; nothing here changes a model.)")


def full():
    t_start = time.time()
    p("WESAD evaluation (docs/wesad_plan.md sections 6-8), all 15 subjects, run once.")
    p(f"code {code}; config {CONFIG['version']}; wesad/arousal blocks frozen {A['frozen']}")
    p(f"amended {A['amended']}")
    p("Data: WESAD (Schmidt et al., ICMI 2018). DEVELOPMENT data for the PPG, EDA, temperature and arousal code;")
    p("leave-one-subject-out protects the classifier, not the feature code. The held-out test is our own protocol recordings.")
    p("Windows 180 s every 30 s, overlapping by 150 s and not independent: the subject is the unit of inference.")
    p("ECG causal monitoring filter, 50 Hz notch, tp3 detector at 256 Hz. Logistic regression, C 1, balanced class weights,")
    p(f"threshold 0.5; z-scores against each subject's reference half of the baseline; bootstrap over subjects, "
      f"{A['bootstrap']} resamples, seed {A['seed']}.")
    p("Stress is the positive class. Se = classified stress windows called stress; Sp = classified negative windows called")
    p("negative; P+ = windows called stress that were stress. acc and F1 (class-averaged, as Schmidt et al.) are over")
    p("CLASSIFIED windows only: read them with the rejection rates. A window is classified only when every feature of the")
    p("model was reported. Pooled values: value [95% interval, bootstrap over subjects].\n")
    p("Models (23 Nov amendment applied):")
    for m, b in A["models"].items():
        p(f"  {m:11s} {' + '.join(b):40s} {', '.join(arousal.model_columns(b))}")
    p("")
    recordings_section()
    p("")
    availability_section()

    primary = {m: run(m, b)[0] for m, b in A["models"].items()}

    p("\n== 3. PRIMARY: second half of the baseline against stress, leave-one-subject-out, pooled over windows")
    pooled_header()
    for m, r in primary.items():
        pooled_line(m, r)
    p("\n   per subject: median [min, max] over the n subjects where the score is defined (Se needs classified stress")
    p("   windows, Sp classified baseline windows, the others both)")
    ps_all = {m: spread_line(m, r) for m, r in primary.items()}
    p("\n   per subject balanced accuracy (%), with (classified stress / classified baseline windows)")
    p(f"  {'subject':8s}" + "".join(f"{m:>20s}" for m in primary))
    for s in ALL:
        cells = []
        for m in primary:
            ps = ps_all[m]
            ba = ps.loc[s, "balanced_accuracy"] if s in ps.index else np.nan
            npos = int(ps.loc[s, "n_positive"]) if s in ps.index else 0
            nneg = int(ps.loc[s, "n_negative"]) if s in ps.index else 0
            cells.append(f"{pct(ba)} ({npos:2d}/{nneg:2d})")
        p(f"  {s:8s}" + "".join(f"{c:>20s}" for c in cells))
    p("\n   coefficient over the 15 folds, median [min, max] (z-score units; positive = higher in stress)")
    for m in A["models"]:
        _, folds, cols = run(m, A["models"][m])
        co = pd.DataFrame([f["coef"] for f in folds.values()])
        p(f"  {m}: " + "; ".join(f"{c} {co[c].median():+.2f} [{co[c].min():+.2f}, {co[c].max():+.2f}]" for c in cols))

    p("\n== 4. ABLATION (descriptive; with 15 subjects no difference between modalities is called significant)")
    groups = {"single modalities": {m: primary[m] for m in ("ECG", "BVP", "EDA", "TEMP")}}
    for top in ("All four", "Wrist-only"):
        g = {top: primary[top]}
        for b in A["models"][top]:
            g[f"{top} - {b}"] = run(f"{top} - {b}", [x for x in A["models"][top] if x != b])[0]
        groups[top] = g
    p("  (single modalities on their own windows: section 3, rows ECG, BVP, EDA, TEMP)")
    for gname, g in groups.items():
        if gname != "single modalities":
            p(f"\n  -- {gname} with each modality removed: on each model's own windows")
            pooled_header()
            for m, r in g.items():
                pooled_line(m, r)
        c = arousal.common_windows(g)
        p(f"\n  -- {gname}: on the windows every model of the group classified (nothing rejected by construction; no interval)")
        pooled_header()
        for m, r in c.items():
            pooled_line(m, r, boot=False)
        ps = {m: arousal.per_subject(r)["balanced_accuracy"].dropna().astype(float) for m, r in c.items()}
        p("     per subject balanced accuracy on these windows, median [min, max]: "
          + "; ".join(f"{m} {100 * v.median():.1f} [{100 * v.min():.1f}, {100 * v.max():.1f}] n={len(v)}"
                      for m, v in ps.items() if len(v)))
    p("\n  -- the six primary models on the windows all six classified")
    pooled_header()
    for m, r in arousal.common_windows(primary).items():
        pooled_line(m, r, boot=False)

    p("\n== 5. B1: the primary models (each fold's model, unchanged) on the test subject's other conditions:")
    p("   share called stress (%) [classified windows, share rejected %]. Baseline is always first; a model that only")
    p("   learned 'later in the session' calls amusement and meditation stress. The baseline column is 1 - Sp.")
    orders = {s: META[s]["order"] for s in ALL}
    cond = ("amusement", "meditation_1", "meditation_2", "baseline")
    p(f"  {'model':12s} {'order (subjects)':22s}" + "".join(f"{k:>24s}" for k in cond))
    for m, r in primary.items():
        for oname, subs in (("all", ALL), ("stress_first", [s for s in ALL if orders[s] == "stress_first"]),
                            ("amusement_first", [s for s in ALL if orders[s] == "amusement_first"])):
            rr = r[r["subject"].isin(subs)]
            cells = []
            for k in cond:
                c_ = arousal.called_positive(rr, k)
                cells.append(f"{pct(c_['share'])} [{c_['n']:4d}, {pct(c_['rejected']).strip():>5s}]")
            p(f"  {m:12s} {oname + f' ({len(subs)})':22s}" + "".join(f"{x:>24s}" for x in cells))

    p("\n== 6. B2: stress against non-stress (second half of baseline + amusement), models retrained, leave-one-subject-out")
    p("   The binary task of Schmidt et al. 2018; accuracy and class-averaged F1 are their metrics.")
    pooled_header()
    b2 = {m: run(m, b, negative=NEG_B2)[0] for m, b in A["models"].items()}
    for m, r in b2.items():
        pooled_line(m, r, negative=NEG_B2)
    p("   per subject:")
    for m, r in b2.items():
        spread_line(m, r, negative=NEG_B2)
    maj = lambda s: (s["tn"] + s["fp"]) / max(1, s["tn"] + s["fp"] + s["tp"] + s["fn"])
    p("   majority-class accuracy ('non-stress' always) on each model's classified windows: "
      + "; ".join(f"{m} {pct(maj(arousal.scores(r, positive=POS, negative=NEG_B2))).strip()}%" for m, r in b2.items()))

    p("\n== 7. Comparison with Schmidt et al. 2018 (plan section 8), and why it is loose")
    p("   Theirs (paper, Table 4; stress against baseline + amusement): best 93.12% accuracy, F1 91.47, LDA on all chest")
    p("   physiological signals (ECG, EDA, EMG, RESP, TEMP); wrist physiological signals at best 88.33% (random forest),")
    p("   86.46% with LDA; majority class 69.94%.")
    for m in A["models"]:
        s = arousal.scores(b2[m], positive=POS, negative=NEG_B2)
        p(f"   Ours, B2, {m:10s}: accuracy {pct(s['accuracy']).strip()}%, F1 {pct(s['f1_macro']).strip()}, balanced accuracy "
          f"{pct(s['balanced_accuracy']).strip()}%, on classified windows; rejected {pct(s['rejected_positive']).strip()}% "
          f"of stress and {pct(s['rejected_negative']).strip()}% of non-stress windows")
    p("   Differences: their windows are 60 s shifted by 0.25 s, ours 180 s every 30 s; their baseline is all 20 min, ours")
    p("   only its second half (the first half is the reference and is never classified); we z-score against that")
    p("   reference, they describe no normalisation; we use no EMG or RESP; logistic regression, not LDA; we reject")
    p("   windows with a withheld feature, they reject none. Our 'All four' is chest ECG with wrist BVP, EDA and TEMP,")
    p("   neither of their sensor sets; our Wrist-only is the closest to their wrist result. A figure above or below")
    p("   theirs is not described as beating or missing their result.")

    p("\n== 8. Secondary models (primary task: second half of the baseline against stress)")
    swap = lambda cols: [("eda_wrist.scr_rate_05" if c == "eda_wrist.scr_rate" else c) for c in cols]
    sec = {"B3 ECG (ECG-full)": run("B3 ECG", ["ecg_full"])[0],
           "B3 All four (ECG-full)": run("B3 All four", ["ecg_full", "bvp_primary", "eda_wrist", "temp_wrist"])[0],
           "B4 EDA chest": run("B4 EDA chest", ["eda_chest"])[0],
           "B4 TEMP chest": run("B4 TEMP chest", ["temp_chest"])[0]}
    for m in ("EDA", "Wrist-only", "All four"):
        sec[f"B5 {m} (SCR 0.05 uS)"] = run(f"B5 {m}", cols=swap(arousal.model_columns(A["models"][m])))[0]
    pooled_header()
    for m, r in sec.items():
        pooled_line(m, r)
    p("   per subject:")
    for m, r in sec.items():
        spread_line(m, r)
    p("   B4 chest TEMP is withheld for S2 and S17 by design (the authors' note), so all their windows are rejected.")
    for a, b in (("ECG", "B3 ECG (ECG-full)"), ("All four", "B3 All four (ECG-full)"), ("EDA", "B4 EDA chest"), ("TEMP", "B4 TEMP chest")):
        p(f"   {a} against {b}, on the windows both classified:")
        pooled_header()
        for m, r in arousal.common_windows({a: primary[a], b: sec[b]}).items():
            pooled_line(m, r, boot=False)

    p("\n== 9. A1: wrist pulses against chest ECG beats (development result for the PPG code; windows overlap; descriptive)")
    p(*A1_HEAD, sep="\n")
    allt = pd.concat([t.assign(subject=s) for s, t in T.items()])
    p("   all 15 subjects pooled, by part:")
    for k in PARTS:
        g = allt[allt["part"] == k]
        if len(g):
            p(f"  {k:13s} " + a1_line(g))
    p("   per subject, Se / P+ (%) by part:")
    p(f"  {'subject':8s}" + "".join(f"{k[:12]:>14s}" for k in PARTS))
    for s, t in T.items():
        cells = []
        for k in PARTS:
            g = t[t["part"] == k]
            se = g["match.tp"].sum() / max(1, g["match.beats"].sum())
            pp = g["match.tp"].sum() / max(1, g["match.pulses"].sum())
            cells.append(f"{100 * se:5.1f}/{100 * pp:5.1f}" if len(g) else "n/a")
        p(f"  {s:8s}" + "".join(f"{c:>14s}" for c in cells))
    a2_section("\n== 10. A2: apparent ECG-beat-to-wrist-pulse delay along the recording (NOT pulse arrival time;")
    p(f"\nrun time {time.time() - t_start:.0f} s")
    return "wesad_evaluation.txt"


name = pilot() if args.pilot else full()
text = out.getvalue()
print(text)
dest = pathlib.Path(args.out) if args.out else HERE / "analysis" / name
dest.write_text(text)
print(f"saved {dest}")
