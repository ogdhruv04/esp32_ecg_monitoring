"""AF screening: is the rhythm in a 30 s window irregular in the way atrial
fibrillation is?

A SCREENING label, not a diagnosis. It reads beat timing and the ectopic
labels only; it never looks at P waves, so it cannot tell AF from any other
irregularly irregular rhythm, and it cannot see AF conducted regularly.

One window is processed ON ITS OWN, as the recordings it was developed on
were: filter and detector start cold, and the beats of the detector's 2 s
warm-up are left out. From what remains,

  rr          intervals between successive detected beats, seconds. ALL of
              them: the NN cleaning used for HRV drops any interval that
              differs more than 20% from the one before, which is exactly the
              irregularity looked for here. An interval across lost samples is
              a break, and nothing is differenced or paired across a break.
  mean_rr     mean interval, s
  ln_nrmssd   ln(RMSSD / mean RR)
  ln_cv       ln(SD / mean RR)
  ln_nmasd    ln(median |successive difference| / median RR): unlike RMSSD,
              unmoved by a few ectopic beats in an otherwise regular rhythm
  ln_sd1_sd2  ln(SD1 / SD2) of the Poincare plot (Brennan et al. 2001): near 0
              when successive intervals are unrelated, as in AF; strongly
              negative when the spread is slow drift
  tpr         turning-point ratio: the share of interior intervals that are a
              local maximum or minimum. 2/3 for a random series, lower for a
              rhythm with structure (used for AF by Dash et al. 2009; that
              citation is from memory and has not been checked)
  cosen       coefficient of sample entropy, after Lake & Moorman 2011:
              sample entropy with m = 1, made comparable across tolerances and
              heart rates: -ln(A / B) + ln(2 r) - ln(mean RR), r and RR in
              seconds. r starts at `cosen_r_s` and grows in steps of
              `cosen_r_step_s` until A reaches `cosen_min_a` matches. Written
              from the published idea, not checked line by line against the
              paper: the definition is the code below.
  v_share     beats labelled V by algorithms/ectopic.py / beats
  s_share     beats labelled S (early, normal shape) / beats. As a label S is
              not usable (P+ 23% on MIT-BIH DS2); as a count it says how many
              beats came early
  ect_und     beats the ectopic step could not judge / beats. About the first
              17 beats of a cold start are in this group
  flag_share  beats the detector could not time (flagged) / beats

No feature is a count that grows with the length of the window.

GATE. A window with fewer than `min_rr` intervals, or with no cosen, is not
judged: its label is "~" (cannot tell), the same label the model gives a
window it takes for noise.

MODEL. af_model.json, written by validate_af.py freeze: class probabilities
for N (normal), A (AF), O (other rhythm), ~ (noisy), developed on the
PhysioNet/CinC 2017 training set. The label is the most probable class.
Settings: config.json "af".
"""
import json, math, os
import numpy as np
from .core import CONFIG
from . import ectopic, frontend

CFG = CONFIG.get("af", {})
FEATURES = ["mean_rr", "ln_nrmssd", "ln_cv", "ln_nmasd", "ln_sd1_sd2", "tpr", "cosen",
            "v_share", "s_share", "ect_und", "flag_share"]
ECTOPIC_FEATURES = ["v_share", "s_share", "ect_und"]
CLASSES = ["N", "A", "O", "~"]
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "af_model.json")
_TINY = 1e-6


def _runs(rr):
    """Maximal stretches of finite intervals."""
    out, cur = [], []
    for v in rr:
        if v == v:
            cur.append(v)
        else:
            if cur:
                out.append(np.array(cur))
            cur = []
    if cur:
        out.append(np.array(cur))
    return out


def cosen(runs, mean_rr, cfg=None):
    """Coefficient of sample entropy of runs of successive intervals (s).
    NaN when even the widest tolerance gives fewer than cosen_min_a matches."""
    cfg = {**CFG, **(cfg or {})}
    t2 = [np.lib.stride_tricks.sliding_window_view(r, 2) for r in runs if len(r) >= 2]
    if not t2:
        return math.nan
    t2 = np.concatenate(t2)
    i, j = np.triu_indices(len(t2), 1)
    d1 = np.abs(t2[i, 0] - t2[j, 0])                 # distance of the length-1 templates
    d2 = np.maximum(d1, np.abs(t2[i, 1] - t2[j, 1]))  # Chebyshev distance of the length-2 ones
    r = cfg["cosen_r_s"]
    while r <= cfg["cosen_r_max_s"] + 1e-12:
        a = int(np.count_nonzero(d2 <= r))
        if a >= cfg["cosen_min_a"]:
            b = int(np.count_nonzero(d1 <= r))
            return -math.log(a / b) + math.log(2.0 * r) - math.log(mean_rr)
        r += cfg["cosen_r_step_s"]
    return math.nan


def rr_features(rr, cfg=None):
    """The timing features of one window from its successive intervals in
    seconds (NaN = a break). Returns a dict that always has n_rr; the other
    keys are present only when there are at least 3 intervals."""
    rr = np.asarray(rr, dtype=float)
    v = rr[np.isfinite(rr)]
    out = {"n_rr": int(len(v))}
    if len(v) < 3:
        return out
    runs = _runs(rr)
    d = np.concatenate([np.diff(r) for r in runs]) if runs else np.zeros(0)
    a = np.concatenate([r[:-1] for r in runs]); b = np.concatenate([r[1:] for r in runs])
    mean = float(v.mean())
    out["mean_rr"] = mean
    out["ln_cv"] = math.log(max(float(v.std(ddof=1)) / mean, _TINY))
    if len(d) >= 2:
        out["ln_nrmssd"] = math.log(max(math.sqrt(float(np.mean(d * d))) / mean, _TINY))
        out["ln_nmasd"] = math.log(max(float(np.median(np.abs(d))) / float(np.median(v)), _TINY))
        sd1 = float(np.std((a - b) / math.sqrt(2.0), ddof=1)); sd2 = float(np.std((a + b) / math.sqrt(2.0), ddof=1))
        out["ln_sd1_sd2"] = math.log(max(sd1, _TINY) / max(sd2, _TINY))
    turn = inner = 0
    for r in runs:
        if len(r) >= 3:
            turn += int(np.count_nonzero((r[1:-1] - r[:-2]) * (r[1:-1] - r[2:]) > 0)); inner += len(r) - 2
    if inner:
        out["tpr"] = turn / inner
    c = cosen(runs, mean, cfg)
    if c == c:
        out["cosen"] = c
    return out


def features(beats, labels, fs, cfg=None):
    """Features of one cold-started window from the detector's beats and their
    ectopic labels (algorithms.ectopic.classify), warm-up beats left out."""
    cfg = {**CFG, **(cfg or {})}
    keep = [k for k, b in enumerate(beats) if b["pos"] / fs >= cfg["warmup_s"]]
    out = {"n_beats": len(keep)}
    if not keep:
        out["n_rr"] = 0
        return out
    pos = np.array([beats[k]["pos"] for k in keep], dtype=float) / fs
    rr = np.diff(pos)
    for q, k in enumerate(keep[1:]):
        if beats[k]["gap"]:
            rr[q] = np.nan
    out.update(rr_features(rr, cfg))
    lab = [labels[k]["label"] for k in keep]
    n = len(keep)
    out["v_share"] = lab.count("V") / n
    out["s_share"] = lab.count("S") / n
    out["ect_und"] = lab.count("U") / n
    out["flag_share"] = sum(1 for k in keep if beats[k]["flagged"]) / n
    return out


def judged(f, cfg=None, names=FEATURES):
    """None when the window can be judged, otherwise why not."""
    cfg = {**CFG, **(cfg or {})}
    if f.get("n_rr", 0) < cfg["min_rr"]:
        return f"{f.get('n_rr', 0)} beat-to-beat intervals, needs {cfg['min_rr']}"
    missing = [k for k in names if k not in f]
    return f"no {missing[0]}" if missing else None


def window_features(x, fs=frontend.FS, mains=50.0, causal=True, harmonic=False, cfg=None):
    """Raw ECG of ONE window at 256 Hz -> features, from a cold start."""
    x = np.asarray(x, dtype=float)
    y = frontend.filter_ecg(x, fs, mains, causal=causal, harmonic=harmonic)
    beats = frontend.detect(y, fs)
    return features(beats, ectopic.classify(y, beats, fs), fs, cfg)


# ------------------------------------------------------------------- the model
def load_model(path=MODEL_PATH):
    with open(path) as f:
        return json.load(f)


def probabilities(model, f):
    """Class probabilities of one judged window, in model['classes'] order."""
    x = np.array([f[k] for k in model["features"]], dtype=float)
    if model["kind"] == "logistic":
        z = (x - np.array(model["mean"])) / np.array(model["scale"])
        s = np.array(model["coef"]) @ z + np.array(model["intercept"])
    elif model["kind"] == "trees":
        s = np.array(model["baseline"], dtype=float)
        for round_ in model["rounds"]:
            for c, nodes in enumerate(round_):
                k = 0
                while nodes[k][0] >= 0:                    # [feature, threshold, left, right, value]
                    k = nodes[k][2] if x[nodes[k][0]] <= nodes[k][1] else nodes[k][3]
                s[c] += nodes[k][4]
    else:
        raise ValueError(model["kind"])
    e = np.exp(s - s.max())
    return e / e.sum()


def label_of(model, f):
    """(label, probabilities or None, why withheld or None) of one window's features."""
    why = judged(f, names=model["features"])
    if why:
        return "~", None, why
    p = probabilities(model, f)
    return model["classes"][int(np.argmax(p))], p, None


def screen(x, fs=frontend.FS, mains=50.0, causal=True, harmonic=False, model=None):
    """One 30 s window of raw ECG -> {'label', 'p', 'withheld', 'features'}.
    label is 'N', 'A', 'O' or '~'; withheld says why when the gate, not the
    model, gave '~'."""
    model = model or load_model()
    f = window_features(x, fs, mains, causal, harmonic)
    lab, p, why = label_of(model, f)
    return dict(label=lab, p=None if p is None else {c: float(v) for c, v in zip(model["classes"], p)},
                withheld=why, features=f)
