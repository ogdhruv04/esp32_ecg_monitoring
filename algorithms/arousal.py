"""Arousal index: features z-scored against the wearer's own reference segment,
a logistic regression, and leave-one-subject-out testing
(docs/wesad_plan.md, sections 5 and 6; config block `arousal`).

A feature table is a pandas DataFrame, one row per window, with the columns
`part` (reference, baseline, stress, ...), `t0`, `t1` and one column per
feature named <block>.<feature> ("ecg.hr", "eda_wrist.scl"). NaN = withheld.

    rows, folds = loso(tables, model_columns(["bvp", "eda_wrist", "temp_wrist"]))
    scores(rows)                      # Se, Sp, P+, balanced accuracy, AUC, rejection

The index of a window is the model's log-odds. A window is classified only
when every feature of the model was reported; the others are rejected and
counted. Nothing about the test subject reaches the fit except through their
own reference-segment mean and sd, which a wearer's baseline recording gives.
"""
import numpy as np
import pandas as pd
from .core import CONFIG
from . import hrv

A = CONFIG["arousal"]
HR_MIN = CONFIG["session"]["hr_min_intervals"]
REFERENCE = "reference"


# ------------------------------------------------------------------ columns
def columns(block):
    """Column names of one block: 'ecg_full', 'ecg_time', 'bvp', 'bvp_primary'
    (pr and ln_amp only: the 23 Nov rule-3 amendment), 'eda_wrist',
    'eda_chest', 'temp_wrist', 'temp_chest'."""
    if block.startswith("ecg"):
        return [f"ecg.{f}" for f in A["features"][block]]
    if block.startswith("bvp"):
        return [f"bvp.{f}" for f in A["features"][block]]
    return [f"{block}.{f}" for f in A["features"][block.split("_")[0]]]


def model_columns(blocks):
    return [c for b in blocks for c in columns(b)]


# ------------------------------------------------------------- ECG features
def ecg_features(nn):
    """The plan's ECG features of one NNSeries window: (values, info)."""
    r = hrv(nn)
    ln = lambda k: float(np.log(r[k].value)) if r[k].ok and r[k].value > 0 else np.nan
    val = lambda k: float(r[k].value) if r[k].ok else np.nan
    out = dict(hr=60000.0 / float(np.median(nn.values)) if nn.n_accepted >= HR_MIN else np.nan,
               ln_rmssd=ln("rmssd"), pnn50=val("pnn50"), ln_sdnn=ln("sdnn"), ln_sd2=ln("sd2"),
               ln_lf=ln("lf"), ln_hf=ln("hf"), dfa_alpha1=val("dfa_alpha1"))
    info = dict(beats=nn.n_intervals + 1 if nn.n_intervals else 0, accepted=nn.n_accepted,
                coverage=nn.coverage, valid_s=nn.valid_s)
    return out, info


# ------------------------------------------------------------ normalisation
def reference_stats(table, cols):
    """(mean, sd) of each column over the subject's reference windows; both
    NaN where fewer than min_reference_windows reported the feature."""
    ref = table.loc[table["part"] == REFERENCE, cols]
    n = ref.notna().sum()
    mu, sd = ref.mean(), ref.std(ddof=1)
    few = n < A["min_reference_windows"]
    mu[few] = np.nan; sd[few] = np.nan
    return mu, sd


def sd_floor(sds):
    """Half the median reference sd over the given (training) subjects."""
    return A["sd_floor_share"] * pd.concat(sds, axis=1).median(axis=1, skipna=True)


def zscore(table, cols, mu, sd, floor):
    """The table with its feature columns replaced by clipped z-scores."""
    den = np.maximum(sd.to_numpy(dtype=float), floor.reindex(cols).to_numpy(dtype=float))   # NaN if either is
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (table[cols].to_numpy(dtype=float) - mu.to_numpy(dtype=float)) / den
    z[~np.isfinite(z)] = np.nan
    out = table.copy()
    out[cols] = np.clip(z, -A["z_clip"], A["z_clip"])
    return out


# ------------------------------------------------------------------ testing
def fit(X, y):
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=A["C"], class_weight=A["class_weight"], max_iter=1000).fit(X, y)


def loso(tables, cols, positive=("stress",), negative=("baseline",)):
    """Leave-one-subject-out. tables: {subject: feature table}. Returns
    (rows, folds): rows has one line per window of every part except the
    reference, with `complete`, `index` (log-odds) and `pred` (1 = positive);
    folds has the fitted coefficients of each fold."""
    cols = list(cols)
    stats = {s: reference_stats(t, cols) for s, t in tables.items()}
    rows, folds = [], {}
    for test in tables:
        train = [s for s in tables if s != test]
        floor = sd_floor([stats[s][1] for s in train])
        Z = {s: zscore(tables[s], cols, *stats[s], floor) for s in tables}
        tr = pd.concat([Z[s] for s in train])
        tr = tr[tr["part"].isin(positive + negative)].dropna(subset=cols)
        y = tr["part"].isin(positive).to_numpy().astype(int)
        if len(np.unique(y)) < 2:
            raise ValueError(f"fold {test}: the training subjects give only one class for {cols}")
        model = fit(tr[cols].to_numpy(), y)
        folds[test] = dict(coef=dict(zip(cols, model.coef_[0])), intercept=float(model.intercept_[0]),
                           n_train=len(tr), n_positive=int(y.sum()))
        te = Z[test][Z[test]["part"] != REFERENCE]
        ok = te[cols].notna().all(axis=1).to_numpy()
        index = np.full(len(te), np.nan)
        if ok.any():
            index[ok] = model.decision_function(te.loc[ok, cols].to_numpy())
        logit_thr = float(np.log(A["threshold"] / (1 - A["threshold"])))
        rows.append(pd.DataFrame(dict(subject=test, part=te["part"].to_numpy(), t0=te["t0"].to_numpy(),
                                      complete=ok, index=index,
                                      pred=np.where(ok, (index > logit_thr).astype(float), np.nan))))
    return pd.concat(rows, ignore_index=True), folds


def scores(rows, positive=("stress",), negative=("baseline",)):
    """Scores of the positive class over the given rows. Never one number:
    Se, Sp and P+ with the rejection rate of each class."""
    pos, neg = rows[rows["part"].isin(positive)], rows[rows["part"].isin(negative)]
    p, n = pos[pos["complete"]], neg[neg["complete"]]
    tp, fn = int((p["pred"] == 1).sum()), int((p["pred"] == 0).sum())
    tn, fp = int((n["pred"] == 0).sum()), int((n["pred"] == 1).sum())
    div = lambda a, b: a / b if b else float("nan")
    se, sp = div(tp, tp + fn), div(tn, tn + fp)
    auc = float("nan")
    if len(p) and len(n):
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(np.r_[np.ones(len(p)), np.zeros(len(n))], np.r_[p["index"], n["index"]]))
    # accuracy and class-averaged F1 (Schmidt et al. 2018's metrics) over the classified windows only;
    # never quoted without the rejection rates beside them
    f1_pos, f1_neg = div(2 * tp, 2 * tp + fp + fn), div(2 * tn, 2 * tn + fn + fp)
    return dict(se=se, sp=sp, ppv=div(tp, tp + fp), balanced_accuracy=(se + sp) / 2, auc=auc,
                accuracy=div(tp + tn, tp + tn + fp + fn), f1_positive=f1_pos, f1_macro=(f1_pos + f1_neg) / 2,
                rejected_positive=div(len(pos) - len(p), len(pos)), rejected_negative=div(len(neg) - len(n), len(neg)),
                n_positive=len(p), n_negative=len(n), tp=tp, fn=fn, tn=tn, fp=fp)


def common_windows(rows_by_model):
    """The rows of each model restricted to the windows that EVERY given model
    classified (plan section 6: comparisons on shared windows)."""
    key = lambda r: pd.MultiIndex.from_frame(r[["subject", "part", "t0"]])
    shared = None
    for r in rows_by_model.values():
        k = key(r[r["complete"]])
        shared = k if shared is None else shared.intersection(k)
    return {m: r[key(r).isin(shared)] for m, r in rows_by_model.items()}


def per_subject(rows, keys=("se", "sp", "balanced_accuracy", "accuracy", "f1_macro", "auc"), **kw):
    """Scores of each subject separately; a subject counts for a key only when
    the key is defined (Se needs classified positives, Sp negatives, the rest both)."""
    out = {}
    for s, g in rows.groupby("subject"):
        sc = scores(g, **kw)
        both = sc["n_positive"] > 0 and sc["n_negative"] > 0
        out[s] = {k: (sc[k] if (both or k in ("se", "sp")) else float("nan")) for k in keys}
        out[s].update(n_positive=sc["n_positive"], n_negative=sc["n_negative"])
    return pd.DataFrame(out).T


def bootstrap(rows, keys=("se", "sp", "balanced_accuracy", "auc"), **kw):
    """95% percentile interval of pooled scores, resampling SUBJECTS."""
    rng = np.random.default_rng(A["seed"])
    by = {s: g for s, g in rows.groupby("subject")}
    names = sorted(by)
    draws = {k: [] for k in keys}
    for _ in range(A["bootstrap"]):
        sample = pd.concat([by[names[i]] for i in rng.integers(0, len(names), len(names))])
        sc = scores(sample, **kw)
        for k in keys:
            draws[k].append(sc[k])
    return {k: tuple(np.nanpercentile(v, [2.5, 97.5])) for k, v in draws.items()}


def called_positive(rows, part):
    """Share of the classified windows of one part that the model calls
    positive (plan B1: false alarms on amusement and meditation), with the
    share rejected."""
    r = rows[rows["part"] == part]
    c = r[r["complete"]]
    return dict(n=len(c), share=float((c["pred"] == 1).mean()) if len(c) else float("nan"),
                rejected=1 - len(c) / len(r) if len(r) else float("nan"))
