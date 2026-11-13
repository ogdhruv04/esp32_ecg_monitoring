#!/usr/bin/env python3
"""AF screening: develop on PhysioNet/CinC 2017, test once on the MIT-BIH AF Database.

    ./validate_af.py cv     --cinc <main>/data/cinc2017      # cross-validation -> analysis/af_cinc_cv.txt
    ./validate_af.py freeze --cinc <main>/data/cinc2017      # fit on all of it -> algorithms/af_model.json
    ./validate_af.py afdb   --afdb <main>/data/afdb          # the external test, ONCE, after the freeze
    ./validate_af.py own    --captures <main>/captures       # our own recordings (no rhythm reference)

DEVELOPMENT: CinC 2017 training set, 8,528 single-lead recordings of 9-61 s at
300 Hz from a hand-held device, labelled N (normal), A (AF), O (other rhythm),
~ (noisy) in REFERENCE-v3.csv. Each recording is one window: its first 30 s
(all of it when shorter), resampled to 256 Hz, the monitoring filter with a
60 Hz notch, CAUSAL as on the phone, detector and ectopic labels from a cold
start (algorithms/af.py).

Cross-validation is BY RECORDING, stratified, 5 folds x 3 repeats. THE DATASET
PUBLISHES NO PATIENT IDENTIFIERS, so recordings of one person can sit on both
sides of a fold and the cross-validated figures may be optimistic. They are
development figures. A recording the gate does not judge is scored as
predicted '~'.

Candidates: multinomial logistic regression on standardised features, and a
small set of gradient-boosted trees (depth 3). Selection, fixed before the
first fit: within a family the setting with the highest mean class-A F1;
between families logistic regression unless the trees score more than 0.02
higher in class-A F1, because a logistic model is 4 x 11 numbers that port to
the phone and can be read.

EXTERNAL TEST: MIT-BIH Atrial Fibrillation Database, 23 records with signals
(one long recording per subject, about 10 h, 250 Hz, analog Holter tape from
1983), none of it used anywhere in this project before. Signal ECG1,
consecutive non-overlapping 30 s windows from sample 0, each resampled to
256 Hz and processed on its own exactly as a CinC recording is. Truth from the
manual rhythm annotations (.atr):
    AF       the whole window is (AFIB
    non-AF   no (AFIB and no (AFL anywhere in it ((N or (J)
    flutter  the whole window is (AFL          - reported apart, not in Se/Sp
    mixed    anything else (a rhythm change)   - reported apart, not in Se/Sp
A window holding 1 s or more of constant samples (the unreadable tape blocks
were replaced by flat zero) is left out and counted. The rhythm before a
record's first annotation (under 1 s) is taken as that annotation's.
Positive = label A; negative = label N or O; '~' = not decided.
    Se = AF windows labelled A / AF windows decided
    Sp = non-AF windows labelled N or O / non-AF windows decided
    coverage = decided / all, next to both; "end to end" counts undecided
    AF windows as missed.
Results per patient and pooled. No setting is changed in response.

Features are cached next to the data (af_cache_*.json), keyed by the settings
that produce them.
"""
import argparse, contextlib, hashlib, io, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["cv", "freeze", "afdb", "own"])
ap.add_argument("--cinc"); ap.add_argument("--afdb"); ap.add_argument("--captures", default="captures")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--rerender", action="store_true", help="afdb: rebuild the report from the cached single run")
args = ap.parse_args()

import algorithms as A
from algorithms import af, ectopic, frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
WIN_S = A.CONFIG["af"]["window_s"]
CLASSES = af.CLASSES
SEEDS = [0, 1, 2]
LOGISTIC = [dict(family="logistic", C=c, class_weight=w) for c in (0.1, 1.0, 10.0) for w in (None, "balanced")]
TREES = [dict(family="trees", max_iter=n, class_weight=w) for n in (50, 100, 200) for w in (None, "balanced")]
TREE_MARGIN = 0.02
AFDB_NO_SIGNAL = {"00735", "03665"}
FLAT_S = 1.0


def settings_key():
    cfg = {k: v for k, v in A.CONFIG["af"].items() if k not in ("frozen", "what", "tuned_on", "model")}
    ect = {k: v for k, v in A.CONFIG["ectopic"].items() if k not in ("frozen", "what", "tuned_on")}
    blob = json.dumps([cfg, ect, A.core.PT.CONFIG["detector"], A.core.PT.CONFIG["version"], af.FEATURES], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def header(extra=()):
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "algorithms", "pan_tompkins.py", "tp2_config.json",
                            "validate_af.py"], capture_output=True, text=True).stdout.strip()
    print(f"# ./validate_af.py {' '.join(sys.argv[1:])}")
    print(f"# commit {commit}{' + uncommitted changes' if dirty else ''}; detector {A.core.PT.CONFIG['version']}; "
          f"af settings {json.dumps({k: v for k, v in A.CONFIG['af'].items() if k not in ('what', 'tuned_on')})}")
    print(f"# features: {' '.join(af.FEATURES)}")
    for line in extra:
        print(f"# {line}")
    print()


# ------------------------------------------------------------------ CinC 2017
def cinc_one(job):
    rec, d = job
    import wfdb
    r = wfdb.rdrecord(f"{d}/training2017/{rec}")
    x = r.p_signal[:, 0]
    fs = float(r.fs)
    x = x[:int(round(WIN_S * fs))]
    return rec, len(r.p_signal) / fs, af.window_features(frontend.resample(x, fs), FS, 60.0, causal=True)


def cinc_features():
    d = args.cinc or sys.exit("--cinc <dir with training2017/ and REFERENCE-v3.csv> is required")
    labels = dict(l.strip().split(",") for l in open(f"{d}/REFERENCE-v3.csv") if l.strip())
    cache = pathlib.Path(d) / f"af_cache_cinc_{settings_key()}.json"
    if cache.exists():
        rows = json.loads(cache.read_text())
    else:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            res = pool.map(cinc_one, [(rec, d) for rec in sorted(labels)], chunksize=50)
        rows = [dict(rec=rec, len_s=n, f=f) for rec, n, f in res]
        cache.write_text(json.dumps(rows))
    for r in rows:
        r["y"] = labels[r["rec"]]
    return rows


def make(cfg):
    if cfg["family"] == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(C=cfg["C"], class_weight=cfg["class_weight"], max_iter=2000))
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.1, max_iter=cfg["max_iter"],
                                          class_weight=cfg["class_weight"], early_stopping=False, random_state=0)


def f1s(y, p):
    """F1 per class, in CLASSES order."""
    out = []
    for c in CLASSES:
        tp = int(np.sum((y == c) & (p == c))); n_ref = int(np.sum(y == c)); n_pred = int(np.sum(p == c))
        out.append(2 * tp / (n_ref + n_pred) if n_ref + n_pred else float("nan"))
    return np.array(out)


def cross_validate(rows, cfg, names):
    """Per-fold F1 per class (folds x 4) and the out-of-fold labels of the first repeat."""
    from sklearn.model_selection import StratifiedKFold
    y = np.array([r["y"] for r in rows])
    ok = np.array([af.judged(r["f"], names=names) is None for r in rows])
    X = np.array([[r["f"].get(k, np.nan) for k in names] for r in rows])
    folds, first = [], None
    for seed in SEEDS:
        pred = np.full(len(rows), "~", dtype=object)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            m = make(cfg).fit(X[tr][ok[tr]], y[tr][ok[tr]])
            q = pred[te]; q[ok[te]] = m.predict(X[te][ok[te]]); pred[te] = q
            folds.append(f1s(y[te], pred[te]))
        if first is None:
            first = pred
    return np.array(folds), first


def name_of(cfg):
    if cfg["family"] == "logistic":
        return f"logistic C={cfg['C']:g} weights={cfg['class_weight'] or 'none'}"
    return f"trees n={cfg['max_iter']} depth=3 weights={cfg['class_weight'] or 'none'}"


def select(results):
    """results: list of (cfg, folds). Returns (chosen cfg, best logistic, best trees)."""
    def best(fam):
        return max((q for q in results if q[0]["family"] == fam), key=lambda q: q[1][:, 1].mean())
    lo, tr = best("logistic"), best("trees")
    chosen = tr if tr[1][:, 1].mean() - lo[1][:, 1].mean() > TREE_MARGIN else lo
    return chosen[0], lo, tr


def run_cv():
    rows = cinc_features()
    y = np.array([r["y"] for r in rows])
    ok = np.array([af.judged(r["f"]) is None for r in rows])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        header(["PhysioNet/CinC 2017 training set, REFERENCE-v3 labels; first 30 s of each recording; causal filter, 60 Hz notch.",
                "Cross-validation BY RECORDING (no patient identifiers are published): figures may be optimistic.",
                "5 folds x 3 repeats (seeds 0 1 2). F1 = mean over the 15 folds; +- = sd over the 15 folds."])
        print(f"recordings {len(rows)}: " + ", ".join(f"{c} {int(np.sum(y == c))}" for c in CLASSES))
        print(f"judged by the gate {int(ok.sum())} ({100 * ok.mean():.1f}%); not judged, scored as predicted '~': "
              + ", ".join(f"{c} {int(np.sum((y == c) & ~ok))}" for c in CLASSES))
        ln = np.array([r["len_s"] for r in rows])
        print(f"recording length: median {np.median(ln):.0f} s, {100 * np.mean(ln > WIN_S + 0.5):.1f}% longer than {WIN_S:g} s (cut to their first {WIN_S:g} s)")
        nb = np.array([r["f"].get("n_rr", 0) for r in rows])
        print(f"beat-to-beat intervals per recording after the warm-up: median {np.median(nb):.0f}, 5th-95th pct {np.percentile(nb, 5):.0f}-{np.percentile(nb, 95):.0f}")
        eu = np.array([r["f"]["ect_und"] for r in rows if "ect_und" in r["f"]])
        print(f"share of beats the ectopic step could not judge (cold start): median {100 * np.median(eu):.0f}%\n")

        print("feature medians by class (judged recordings):")
        print(f"{'':12}" + "".join(f"{c:>9}" for c in CLASSES))
        for k in af.FEATURES:
            print(f"{k:12}" + "".join(f"{np.median([r['f'][k] for r, o in zip(rows, ok) if o and r['y'] == c]):9.3f}" for c in CLASSES))
        print()

        print(f"{'model':42} {'F1 N':>6} {'F1 A':>6} {'F1 O':>6} {'F1 ~':>6} | {'mean N,A,O':>10} {'A +-':>6}")
        results = []
        for cfg in LOGISTIC + TREES:
            folds, first = cross_validate(rows, cfg, af.FEATURES)
            results.append((cfg, folds, first))
            m = folds.mean(axis=0)
            print(f"{name_of(cfg):42} {m[0]:6.3f} {m[1]:6.3f} {m[2]:6.3f} {m[3]:6.3f} | {m[:3].mean():10.3f} {folds[:, 1].std(ddof=1):6.3f}")
        chosen, lo, tr = select([(c, f) for c, f, _ in results])
        print(f"\nbest logistic: {name_of(lo[0])} (class-A F1 {lo[1][:, 1].mean():.3f}); best trees: {name_of(tr[0])} (class-A F1 {tr[1][:, 1].mean():.3f}); "
              f"difference {tr[1][:, 1].mean() - lo[1][:, 1].mean():+.3f}, margin for choosing trees {TREE_MARGIN}")
        print(f"CHOSEN: {name_of(chosen)}\n")

        folds, first = next((f, p) for c, f, p in results if c is chosen)
        m, s = folds.mean(axis=0), folds.std(axis=0, ddof=1)
        print("=== the chosen model, cross-validated on CinC 2017 by recording ===")
        print("F1 per class: " + ", ".join(f"{c} {a:.3f} +- {b:.3f}" for c, a, b in zip(CLASSES, m, s)))
        print(f"mean of N, A, O (the challenge's score): {m[:3].mean():.3f}. For context only: the challenge's top entries scored 0.83, on a hidden")
        print("test set of other recordings, whole recordings, with waveform features. That set is not public; the two numbers are not comparable.")
        print("\nout-of-fold confusion, first repeat (rows = reference, columns = predicted; '~' includes recordings the gate did not judge):")
        print(f"{'':6}" + "".join(f"{c:>7}" for c in CLASSES) + f"{'total':>8}")
        for c in CLASSES:
            print(f"{c:6}" + "".join(f"{int(np.sum((y == c) & (first == d))):7d}" for d in CLASSES) + f"{int(np.sum(y == c)):8d}")
        a_ref, a_pred = y == "A", first == "A"
        dec = first != "~"
        print(f"class A as a screen, same out-of-fold labels: Se {100 * np.sum(a_ref & a_pred) / np.sum(a_ref & dec):.1f}% and "
              f"Sp {100 * np.sum(~a_ref & dec & ~a_pred) / np.sum(~a_ref & dec):.1f}% on the {100 * dec.mean():.1f}% of recordings labelled N, A or O; "
              f"P+ {100 * np.sum(a_ref & a_pred) / np.sum(a_pred):.1f}%; "
              f"end-to-end Se {100 * np.sum(a_ref & a_pred) / np.sum(a_ref):.1f}%")
        fa = {c: int(np.sum((y == c) & a_pred)) for c in "NO~"}
        print(f"recordings labelled A that are not AF: {fa['N']} of {int(np.sum(y == 'N'))} normal, {fa['O']} of {int(np.sum(y == 'O'))} other rhythm, {fa['~']} of {int(np.sum(y == '~'))} noisy")

        print("\n=== what the feature groups add (the chosen setting, same folds) ===")
        groups = [("all features", af.FEATURES),
                  ("without the ectopic features (v_share, s_share, ect_und)", [k for k in af.FEATURES if k not in af.ECTOPIC_FEATURES]),
                  ("without v_share only", [k for k in af.FEATURES if k != "v_share"]),
                  ("timing features only (no ectopic, no flag_share)", [k for k in af.FEATURES if k not in af.ECTOPIC_FEATURES + ["flag_share"]])]
        print(f"{'features':58} {'F1 N':>6} {'F1 A':>6} {'F1 O':>6} {'F1 ~':>6} | {'mean N,A,O':>10}")
        for label, names in groups:
            f2, _ = cross_validate(rows, chosen, names)
            m2 = f2.mean(axis=0)
            print(f"{label:58} {m2[0]:6.3f} {m2[1]:6.3f} {m2[2]:6.3f} {m2[3]:6.3f} | {m2[:3].mean():10.3f}")
    text = buf.getvalue(); print(text, end="")
    (HERE / "analysis" / "af_cinc_cv.txt").write_text(text); print(f"saved {HERE / 'analysis' / 'af_cinc_cv.txt'}")
    return rows, chosen


# --------------------------------------------------------------------- freeze
def export(model, cfg):
    """The fitted sklearn model as plain numbers (algorithms/af.py reads them)."""
    if cfg["family"] == "logistic":
        sc, lr = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
        order = [list(lr.classes_).index(c) for c in CLASSES]
        return dict(kind="logistic", mean=sc.mean_.tolist(), scale=sc.scale_.tolist(),
                    coef=lr.coef_[order].tolist(), intercept=lr.intercept_[order].tolist())
    order = [list(model.classes_).index(c) for c in CLASSES]
    rounds = []
    for it in model._predictors:
        per = []
        for c in order:
            nd = it[c].nodes
            per.append([[-1 if n["is_leaf"] else int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]),
                         float(n["value"])] for n in nd])
        rounds.append(per)
    return dict(kind="trees", baseline=np.ravel(model._baseline_prediction)[order].tolist(), rounds=rounds)


def run_freeze():
    import datetime
    if A.CONFIG["af"].get("frozen"):
        sys.exit("refusing: config.json 'af' is already frozen")
    rows, chosen = run_cv()
    ok = [r for r in rows if af.judged(r["f"]) is None]
    X = np.array([[r["f"][k] for k in af.FEATURES] for r in ok]); y = np.array([r["y"] for r in ok])
    m = make(chosen).fit(X, y)
    today = datetime.date.today().isoformat()
    model = dict(version="af1", frozen=today, classes=CLASSES, features=af.FEATURES, **export(m, chosen),
                 setting=name_of(chosen),
                 trained_on=f"PhysioNet/CinC 2017 training set, REFERENCE-v3: the {len(ok)} of {len(rows)} recordings the gate judges "
                            f"({', '.join(f'{c} {int(np.sum(y == c))}' for c in CLASSES)}), first 30 s, causal filter, cold start",
                 selected_by="analysis/af_cinc_cv.txt (cross-validation by recording; no patient identifiers exist)",
                 rule="label = most probable class; a window the gate does not judge is '~'. A = screen positive.")
    # the exported numbers must reproduce sklearn's probabilities
    cols = [list(m.classes_).index(c) for c in CLASSES]
    ref = m.predict_proba(X)[:, cols]
    mine = np.array([af.probabilities(model, r["f"]) for r in ok])
    worst = float(np.abs(ref - mine).max())
    if worst > 1e-9:
        sys.exit(f"exported model differs from the fitted one by {worst:g}")
    with open(af.MODEL_PATH, "w") as f:
        json.dump(model, f, indent=1); f.write("\n")
    cfg_path = HERE / "algorithms" / "config.json"
    c = json.loads(cfg_path.read_text())
    c["af"]["frozen"] = today
    c["af"]["model"] = f"algorithms/af_model.json (af1): {name_of(chosen)}, selected in analysis/af_cinc_cv.txt"
    cfg_path.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    msg = (f"\nFROZEN {today}: {name_of(chosen)} fitted on {len(ok)} recordings -> algorithms/af_model.json; "
           f"exported numbers reproduce the fitted model's probabilities to {worst:.1e} on all of them.\n")
    print(msg, end="")
    with open(HERE / "analysis" / "af_cinc_cv.txt", "a") as f:
        f.write(msg)


# ----------------------------------------------------------------------- AFDB
def afdb_record(job):
    rec, d = job
    import wfdb
    r = wfdb.rdrecord(f"{d}/{rec}", channels=[0]); ann = wfdb.rdann(f"{d}/{rec}", "atr")
    fs = float(r.fs); x = r.p_signal[:, 0]; n = len(x)
    w = int(round(WIN_S * fs))
    # rhythm code per sample: 0 other, 1 AFIB, 2 AFL
    code = np.zeros(n, dtype=np.int8)
    marks = [(int(s), a.strip("\x00")) for s, a in zip(ann.sample, ann.aux_note) if a.strip("\x00").startswith("(")]
    for k, (s, a) in enumerate(marks):
        e = marks[k + 1][0] if k + 1 < len(marks) else n
        code[(0 if k == 0 else s):e] = 1 if a == "(AFIB" else 2 if a == "(AFL" else 0
    model = af.load_model()
    out = []
    for k in range(n // w):
        seg = x[k * w:(k + 1) * w]; c = code[k * w:(k + 1) * w]
        fib, fl = float(np.mean(c == 1)), float(np.mean(c == 2))
        truth = "AF" if fib == 1.0 else "nonAF" if fib == 0.0 and fl == 0.0 else "flutter" if fl == 1.0 else "mixed"
        same = np.flatnonzero(np.diff(seg) != 0)
        edges = np.concatenate([[-1], same, [len(seg) - 1]])
        flat = bool(np.max(np.diff(edges)) >= FLAT_S * fs) or not bool(np.all(np.isfinite(seg)))
        if flat:
            out.append(dict(k=k, truth=truth, label="excluded")); continue
        f = af.window_features(frontend.resample(seg, fs), FS, 60.0, causal=True)
        lab, p, why = af.label_of(model, f)
        out.append(dict(k=k, truth=truth, label=lab, p_a=None if p is None else float(p[model["classes"].index("A")]),
                        gate=why is not None, n_rr=f.get("n_rr", 0)))
    return rec, out


def pct(a, b):
    return f"{100 * a / b:6.2f}" if b else "     -"


def run_afdb():
    d = args.afdb or sys.exit("--afdb <dir> is required")
    if not A.CONFIG["af"].get("frozen") or not os.path.exists(af.MODEL_PATH):
        sys.exit("refusing: the external test is run once, after 'af' is frozen and af_model.json exists")
    model = af.load_model()
    out_path = HERE / "analysis" / "af_afdb_external.txt"
    cache = pathlib.Path(d) / f"af_cache_afdb_{model['version']}_{settings_key()}.json"
    if args.rerender:
        res = json.loads(cache.read_text())
    else:
        if out_path.exists() or cache.exists():
            sys.exit(f"refusing: the external test has been run ({out_path}); --rerender rebuilds the report from the saved labels")
        recs = [r for r in open(f"{d}/RECORDS").read().split() if r not in AFDB_NO_SIGNAL]
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            res = dict(pool.map(afdb_record, [(r, d) for r in recs], chunksize=1))
        cache.write_text(json.dumps(res))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        header([f"MIT-BIH Atrial Fibrillation Database, {len(res)} records with signals (00735 and 03665 have none), signal ECG1.",
                f"EXTERNAL TEST, run once with model {model['version']} frozen {model['frozen']} ({model['setting']}). No setting is changed in response.",
                "30 s windows, non-overlapping, each resampled 250 -> 256 Hz and processed from a cold start; causal filter, 60 Hz notch.",
                "Positive = label A. Se and Sp on decided windows (label N, A or O), with coverage; end to end counts undecided AF windows as missed."])
        tot = {}
        per = []
        for rec in sorted(res):
            c = dict(rec=rec)
            for t in ("AF", "nonAF", "flutter", "mixed"):
                w = [q for q in res[rec] if q["truth"] == t]
                c[t] = dict(n=len(w), excl=sum(q["label"] == "excluded" for q in w), und=sum(q["label"] == "~" for q in w),
                            a=sum(q["label"] == "A" for q in w), o=sum(q["label"] == "O" for q in w), nn=sum(q["label"] == "N" for q in w),
                            gate=sum(bool(q.get("gate")) for q in w))
                for k, v in c[t].items():
                    tot.setdefault(t, {}).setdefault(k, 0); tot[t][k] += v
            per.append(c)

        def line(c):
            af_, na = c["AF"], c["nonAF"]
            af_dec = af_["n"] - af_["excl"] - af_["und"]; na_dec = na["n"] - na["excl"] - na["und"]
            scored = af_["n"] - af_["excl"] + na["n"] - na["excl"]
            return (f"{af_['n'] - af_['excl']:6d} {pct(af_['a'], af_dec)} {pct(af_['a'], af_['n'] - af_['excl'])} | "
                    f"{na['n'] - na['excl']:6d} {pct(na_dec - na['a'], na_dec)} {na['a']:6d} | {pct(af_dec + na_dec, scored)}")

        n_all = sum(tot[t]["n"] for t in tot); n_ex = sum(tot[t]["excl"] for t in tot)
        print(f"windows: {n_all} of 30 s; {n_ex} left out for holding a flat (unreadable) stretch")
        print("by rhythm annotation: " + ", ".join(f"{t} {tot[t]['n'] - tot[t]['excl']}" for t in ("AF", "nonAF", "flutter", "mixed")))
        a, n = tot["AF"], tot["nonAF"]
        a_all, n_all2 = a["n"] - a["excl"], n["n"] - n["excl"]
        a_dec, n_dec = a_all - a["und"], n_all2 - n["und"]
        print("\n=== pooled over all windows ===")
        print(f"AF windows {a_all}: labelled A {a['a']}, O {a['o']}, N {a['nn']}, not decided {a['und']} (of which the gate {a['gate']})")
        print(f"non-AF windows {n_all2}: labelled A {n['a']}, O {n['o']}, N {n['nn']}, not decided {n['und']} (of which the gate {n['gate']})")
        print(f"Se {pct(a['a'], a_dec).strip()}%  Sp {pct(n_dec - n['a'], n_dec).strip()}%  at coverage {pct(a_dec + n_dec, a_all + n_all2).strip()}% "
              f"(AF windows {pct(a_dec, a_all).strip()}%, non-AF {pct(n_dec, n_all2).strip()}%)")
        print(f"end to end: Se {pct(a['a'], a_all).strip()}% of all AF windows; {pct(n['a'], n_all2).strip()}% of all non-AF windows labelled A")
        print(f"P+ {pct(a['a'], a['a'] + n['a']).strip()}% at this database's mix ({pct(a_all, a_all + n_all2).strip()}% of scored windows are AF; "
              f"P+ depends on that share and would be far lower in screening)")
        for t, what in (("flutter", "atrial flutter throughout"), ("mixed", "a rhythm change inside the window")):
            q = tot[t]; m = q["n"] - q["excl"]
            print(f"not in Se/Sp - {what}: {m} windows, labelled A {q['a']} ({pct(q['a'], m).strip()}%), O {q['o']}, N {q['nn']}, not decided {q['und']}")

        print("\n=== per patient (one record each) ===")
        print(f"{'rec':>6} {'AF win':>6} {'Se%':>6} {'e2e%':>6} | {'non-AF':>6} {'Sp%':>6} {'as A':>6} | {'cov%':>6}")
        ses, sps = [], []
        for c in per:
            print(f"{c['rec']:>6} {line(c)}")
            af_, na = c["AF"], c["nonAF"]
            af_dec = af_["n"] - af_["excl"] - af_["und"]; na_dec = na["n"] - na["excl"] - na["und"]
            if af_dec >= 20:
                ses.append((100 * af_["a"] / af_dec, c["rec"]))
            if na_dec >= 20:
                sps.append((100 * (na_dec - na["a"]) / na_dec, c["rec"]))
        print(f"{'pooled':>6} {line(dict(AF=a, nonAF=n))}")
        for name, v in (("Se", ses), ("Sp", sps)):
            vals = np.array([q[0] for q in v])
            low = ", ".join(f"{r} {x:.1f}%" for x, r in sorted(v)[:3])
            print(f"per-patient {name}, patients with 20 or more decided windows of that kind ({len(v)}): median {np.median(vals):.1f}%, "
                  f"range {vals.min():.1f}-{vals.max():.1f}%; lowest: {low}")
    text = buf.getvalue(); print(text, end="")
    out_path.write_text(text); print(f"saved {out_path}")


# -------------------------------------------------------------- own recordings
def run_own():
    if not A.CONFIG["af"].get("frozen"):
        sys.exit("refusing: freeze first")
    model = af.load_model()
    cap = pathlib.Path(args.captures)
    files = [("dual03 chest (ring board)", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv"),
             ("dual03 finger (reference board)", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv"),
             ("tb01", "20261027_173714_testboard01.csv"), ("tb02", "20261027_174352_testboard02.csv")]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        header([f"Our own recordings, model {model['version']} frozen {model['frozen']}. 30 s windows from the first sample, cold start each,",
                "causal filter, 50 and 100 Hz notches. A window with lost samples is left out.",
                "THERE IS NO RHYTHM REFERENCE for these recordings: nobody read their rhythm, no second device labelled it.",
                "The wearers are presumed to be in normal rhythm. So this is a count of labels, not a measured false-alarm rate."])
        w = int(WIN_S * FS); tot = dict(n=0, A=0, O=0, N=0, und=0)
        for name, fn in files:
            val, skips, dup = frontend.load_capture(cap / fn)
            idx = np.cumsum(skips + 1) - 1                     # position by sample index
            n_win = int((idx[-1] + 1) // w)
            print(f"=== {name}: {fn} ===")
            print(f"{len(val)} samples ({len(val) / FS:.1f} s), {int(skips.sum())} lost; {n_win} whole windows")
            for k in range(n_win):
                sel = (idx >= k * w) & (idx < (k + 1) * w)
                if int(sel.sum()) < w:
                    print(f"  window {k}: left out, {w - int(sel.sum())} samples lost"); continue
                s = af.screen(val[sel], FS, 50.0, causal=True, harmonic=True, model=model)
                f = s["features"]
                p = "" if s["p"] is None else "  p: " + " ".join(f"{c} {s['p'][c]:.2f}" for c in model["classes"])
                print(f"  window {k}: {s['label']}{'  (' + s['withheld'] + ')' if s['withheld'] else ''}{p}  | intervals {f.get('n_rr', 0)}, "
                      f"flagged {100 * f.get('flag_share', 0):.0f}%, V {100 * f.get('v_share', 0):.0f}%, early {100 * f.get('s_share', 0):.0f}%")
                tot["n"] += 1; tot["und" if s["label"] == "~" else s["label"]] += 1
            print()
        print(f"all recordings: {tot['n']} windows: N {tot['N']}, O {tot['O']}, A {tot['A']}, not decided {tot['und']}")
        print("dual03's two files are the same 105 s of one person at two sites, so its windows are not independent.")
    text = buf.getvalue(); print(text, end="")
    (HERE / "analysis" / "af_own_recordings.txt").write_text(text); print(f"saved {HERE / 'analysis' / 'af_own_recordings.txt'}")


if __name__ == "__main__":
    {"cv": run_cv, "freeze": run_freeze, "afdb": run_afdb, "own": run_own}[args.mode]()
