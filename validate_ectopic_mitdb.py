#!/usr/bin/env python3
"""Ventricular ectopic beats on MIT-BIH, de Chazal's inter-patient split.

    ./validate_ectopic_mitdb.py --set ds1 --dir <main>/data/mitdb <main>/data/mitdb_heldout [--tune]
    ./validate_ectopic_mitdb.py --set ds2 --dir <main>/data/mitdb <main>/data/mitdb_heldout

DS1 (22 records) is for tuning, DS2 (22 other records, other patients) for
testing; the four paced records are in neither (de Chazal, O'Dwyer, Reilly,
IEEE Trans Biomed Eng 2004). The split is by patient, so no patient's beats
are on both sides.

DS2 IS NOT TRULY HELD OUT HERE. All 48 MIT-BIH records are development data
in this project from 13 Nov 2026: the detector, tp3 and the session rules were
all developed with DS2 records in view. Nothing in algorithms/ectopic.py was
tuned on DS2, and it is run once after the settings are frozen, but the
detector underneath it has seen these records. Read the DS2 figures as a
same-database check on other patients, not as an estimate for new data.

Scoring. AAMI class V = annotation symbols V and E. Detected beats are matched
one-to-one to annotated beats within 150 ms. On DECIDED beats (label N, S or
V): TP = class-V beat labelled V; FN = class-V beat labelled N or S; FP = any
other beat, or an unmatched detection, labelled V. Se and P+ are gross over
the set. COVERAGE = annotated beats that were detected and decided / all
annotated beats, next to them. "End to end" Se also counts as missed the
class-V beats that were not detected or not decided.

MLII lead, 360 -> 256 Hz, the monitoring filter (60 Hz notch), tp3 detector.
Tuning and the headline are under the causal filter (the phone's).

--tune (DS1 only) scores a grid of thresholds and names the one with the highest
F1 averaged over the two filters; the features do not depend on r_v, prem_v or
r_vv, so they are computed once per r_n.

Saves analysis/ectopic_mitdb_<set>[_tuning].txt.
"""
import argparse, contextlib, io, itertools, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--set", choices=["ds1", "ds2"], required=True)
ap.add_argument("--dir", nargs="+", required=True)
ap.add_argument("--tune", action="store_true")
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()

import algorithms as A
from algorithms import ectopic, frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
DS = {"ds1": "101 106 108 109 112 114 115 116 118 119 122 124 201 203 205 207 208 209 215 220 223 230".split(),
      "ds2": "100 103 105 111 113 117 121 123 200 202 210 212 213 214 219 221 222 228 231 232 233 234".split()}
if args.set == "ds2" and (args.tune or not A.CONFIG["ectopic"].get("frozen")):
    sys.exit("refusing: DS2 is run once, after algorithms/config.json 'ectopic' is frozen, and never tuned on")
BEAT = set("NLRejAaJSVEFP/fQ")
V_SYM, S_SYM = set("VE"), set("AaJS")
FILTERS = ["causal", "zero-phase"]
R_N = [0.9, 0.95, 0.97]


def find(rec):
    for d in args.dir:
        if os.path.exists(f"{d}/{rec}.hea"):
            return f"{d}/{rec}"
    sys.exit(f"record {rec} not found in {args.dir}")


def one(job):
    rec, r_ns = job
    import wfdb
    path = find(rec)
    r = wfdb.rdrecord(path); ann = wfdb.rdann(path, "atr")
    names = list(r.sig_name)
    x = frontend.resample(r.p_signal[:, names.index("MLII") if "MLII" in names else 0], float(r.fs))
    sym = [s for s in ann.symbol if s in BEAT]
    at = np.array([s for s, q in zip(ann.sample, ann.symbol) if q in BEAT], dtype=float) / float(r.fs)
    out = dict(rec=rec, n_ann=len(sym), n_v=sum(s in V_SYM for s in sym), n_s=sum(s in S_SYM for s in sym), f={})
    for filt in FILTERS:
        y = frontend.filter_ecg(x, FS, 60.0, causal=(filt == "causal"))
        beats = frontend.detect(y, FS)
        bt = np.array([b["pos"] for b in beats]) / FS
        used = np.zeros(len(at), bool); cls = []          # annotation symbol of each detected beat, "" = unmatched
        for t in bt:
            i = np.searchsorted(at, t); best, bd = -1, 0.151
            for k in (i - 1, i, i + 1):
                if 0 <= k < len(at) and not used[k] and abs(at[k] - t) < bd:
                    best, bd = k, abs(at[k] - t)
            if best >= 0:
                used[best] = True
            cls.append(sym[best] if best >= 0 else "")
        feats = {}
        for rn in r_ns:
            lab = ectopic.classify(y, beats, FS, {"r_n": rn})
            feats[rn] = (np.array([q["r"] for q in lab]), np.array([q["prem"] for q in lab]),
                         np.array([q["label"] == "U" for q in lab]))
        out["f"][filt] = dict(cls=cls, feats=feats, missed_v=int(sum(1 for k, s in enumerate(sym) if s in V_SYM and not used[k])),
                              flagged=float(np.mean([b["flagged"] for b in beats])))
    return out


def score(rows, filt, cfg):
    """Gross and per-record counts for class V (and S) under cfg."""
    tot = dict(tp=0, fp=0, fn=0, und_v=0, missed_v=0, n_v=0, decided=0, n_ann=0, s_tp=0, s_fp=0, s_fn=0)
    per = []
    for r in rows:
        f = r["f"][filt]; rr, prem, und = f["feats"][cfg["r_n"]]
        cls = f["cls"]
        lab = ["U" if u else ectopic.label(a, b, cfg) for a, b, u in zip(rr, prem, und)]
        c = dict(tp=0, fp=0, fn=0, und_v=0, decided=0, s_tp=0, s_fp=0, s_fn=0)
        for l, s in zip(lab, cls):
            v = s in V_SYM
            if l == "U":
                c["und_v"] += v; continue
            if s:
                c["decided"] += 1
            if l == "V":
                c["tp" if v else "fp"] += 1
            elif v:
                c["fn"] += 1
            sv = s in S_SYM
            if l == "S":
                c["s_tp" if sv else "s_fp"] += 1
            elif sv:
                c["s_fn"] += 1
        c.update(missed_v=f["missed_v"], n_v=r["n_v"], n_ann=r["n_ann"], rec=r["rec"], flagged=f["flagged"])
        per.append(c)
        for k in tot:
            tot[k] += c[k]
    return tot, per


def rates(c):
    se = 100 * c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else float("nan")
    pp = 100 * c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else float("nan")
    f1 = 2 * se * pp / (se + pp) if se + pp > 0 else float("nan")
    e2e = 100 * c["tp"] / c["n_v"] if c["n_v"] else float("nan")
    return se, pp, f1, 100 * c["decided"] / c["n_ann"], e2e


def header(recs):
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "algorithms", "pan_tompkins.py", "tp2_config.json",
                            "validate_ectopic_mitdb.py"], capture_output=True, text=True).stdout.strip()
    print(f"# ./validate_ectopic_mitdb.py {' '.join(sys.argv[1:])}")
    print(f"# commit {commit}{' + uncommitted changes' if dirty else ''}; detector {A.core.PT.CONFIG['version']}; "
          f"ectopic settings {json.dumps({k: v for k, v in A.CONFIG['ectopic'].items() if k != 'what'})}")
    print(f"# MIT-BIH {args.set.upper()}, {len(recs)} records: {' '.join(recs)}")
    print("# AAMI class V = V, E. Matching 150 ms. MLII, 256 Hz, 0.5-40 Hz with 60 Hz notch.")
    if args.set == "ds2":
        print("# DS2 is NOT truly held out: all 48 MIT-BIH records are development data in this project (docstring).")
    print()


def main():
    recs = DS[args.set]
    r_ns = R_N if args.tune else [A.CONFIG["ectopic"]["r_n"]]
    import multiprocessing as mp
    with mp.Pool(args.jobs) as pool:
        rows = pool.map(one, [(r, r_ns) for r in recs])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        header(recs)
        if args.tune:
            grid = dict(r_n=R_N, r_v=[0.7, 0.8, 0.9, 0.95], prem_v=[0.85, 0.9, 0.95, 1.0, 9.9], r_vv=[-9.9, 0.4, 0.6, 0.7, 0.8])
            print(f"grid: {json.dumps(grid)}   (prem_v 9.9 = no prematurity needed; r_vv -9.9 = shape alone never decides)")
            print("class V on DS1, gross: Se % / P+ % / F1 / coverage % / end-to-end Se %, causal then zero-phase.")
            print("Sorted by the mean of the two F1 values, top 25. The setting is chosen by that mean, not by the causal F1 alone:")
            print("a setting that only wins under one filter is fitted to that filter's version of these 22 records.\n")
            res = []
            for combo in itertools.product(*grid.values()):
                cfg = {**A.CONFIG["ectopic"], **dict(zip(grid, combo))}
                a = rates(score(rows, "causal", cfg)[0]); b = rates(score(rows, "zero-phase", cfg)[0])
                res.append((0.5 * (a[2] + b[2]), combo, a, b))
            res.sort(key=lambda q: -q[0])
            print(f"{'r_n':>5} {'r_v':>5} {'prem_v':>6} {'r_vv':>5} | {'causal':^36} | {'zero-phase':^36}")
            for _, combo, a, b in res[:25]:
                print(f"{combo[0]:5.2f} {combo[1]:5.2f} {combo[2]:6.2f} {combo[3]:5.2f} | "
                      + " | ".join(f"{q[0]:6.2f} {q[1]:6.2f} {q[2]:6.2f} {q[3]:6.1f} {q[4]:6.2f}" for q in (a, b)))
            best = res[0][1]
            print(f"\nhighest mean F1: r_n {best[0]}, r_v {best[1]}, prem_v {best[2]}, r_vv {best[3]} (mean {res[0][0]:.2f}); "
                  f"highest causal F1 alone: {max(res, key=lambda q: q[2][2])[1]}")
            cur = A.CONFIG["ectopic"]
            print(f"config.json holds: r_n {cur['r_n']}, r_v {cur['r_v']}, prem_v {cur['prem_v']}, r_vv {cur['r_vv']} "
                  f"(prem_s {cur['prem_s']}, rr_keep {cur['rr_keep']}, reseed {cur['reseed']} were set by hand)")
        else:
            cfg = dict(A.CONFIG["ectopic"])
            for filt in FILTERS:
                tot, per = score(rows, filt, cfg)
                se, pp, f1, cov, e2e = rates(tot)
                print(f"=== {filt} filter, class V, gross over {len(recs)} records ===")
                print(f"annotated class-V beats {tot['n_v']}: TP {tot['tp']}, FN {tot['fn']}, FP {tot['fp']}; not decided {tot['und_v']}, not detected {tot['missed_v']}")
                print(f"Se {se:.2f}%  P+ {pp:.2f}%  F1 {f1:.2f}  at coverage {cov:.1f}% of annotated beats;  end-to-end Se {e2e:.2f}%")
                s_se = 100 * tot["s_tp"] / max(1, tot["s_tp"] + tot["s_fn"]); s_pp = 100 * tot["s_tp"] / max(1, tot["s_tp"] + tot["s_fp"])
                print(f"for information, label S against AAMI class S (A a J S), not tuned: Se {s_se:.1f}%  P+ {s_pp:.1f}% "
                      f"(TP {tot['s_tp']}, FN {tot['s_fn']}, FP {tot['s_fp']})")
                print(f"{'rec':>4} {'beats':>6} {'V':>5} {'TP':>5} {'FN':>5} {'FP':>5} {'Se%':>7} {'P+%':>7} {'cov%':>6} {'undecided V':>11} {'missed V':>8} {'flagged%':>8}")
                for c in per:
                    a = rates(c)
                    print(f"{c['rec']:>4} {c['n_ann']:6d} {c['n_v']:5d} {c['tp']:5d} {c['fn']:5d} {c['fp']:5d} {a[0]:7.2f} {a[1]:7.2f} {a[3]:6.1f} "
                          f"{c['und_v']:11d} {c['missed_v']:8d} {100*c['flagged']:8.1f}")
                print()
    text = buf.getvalue(); print(text, end="")
    name = f"ectopic_mitdb_{args.set}{'_tuning' if args.tune else ''}.txt"
    (HERE / "analysis" / name).write_text(text); print(f"saved {HERE / 'analysis' / name}")


if __name__ == "__main__":
    main()
