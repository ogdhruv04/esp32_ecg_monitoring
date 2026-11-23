"""Ectopic beats: shape against the normal beat, and timing against the normal rhythm.

Two things mark a ventricular ectopic beat (a PVC): it does not look like the
wearer's normal beat, and it comes early. Each detected beat gets

  r     its best correlation (over +-CORR_LAG samples) with the NORMAL
        TEMPLATE, the median of the last POL_KEEP beats labelled normal. This
        is not the detector's median beat, which takes every beat: in bigeminy
        half of those are ectopic.
  prem  the interval from the previous beat / the reference interval, the
        median of the last `rr_keep` intervals between two normal beats.

and one label:

  "V"  ventricular ectopic: r < r_v and prem < prem_v, or r < r_vv whatever
       the timing (a very different shape; covers late and interpolated ones)
  "S"  premature with a normal shape: r >= r_n and prem < prem_s
  "N"  everything else that could be judged. Only a beat with r >= r_n that is
       not premature joins the template, and only an interval between two such
       beats joins the reference.
  "U"  undecided: no template yet, a gap in the beat's window or before it,
       or no reference interval yet. The template is seeded by the first
       POL_MIN beats the detector itself could time (unflagged, so already
       alike and aligned); seeding from the very first detections, which
       include whatever the detector picks up while it settles, gave a
       template that normal beats matched poorly for the first 20 s.

If `reseed` beats in a row fail to match the template (the normal beat itself
has changed: posture, a conduction change) the template is rebuilt from the
last POL_KEEP beats and the reference interval starts again, so beats are
undecided until two normal beats in a row are seen. Two limits follow. A run
of ventricular beats that long is learned as normal. And in sustained bigeminy
the rebuilt template is half ventricular, no two normal beats are adjacent,
and every later beat stays undecided: coverage falls, labels are not invented.
Rebuilding only from beats the detector could time avoided the second but
scored lower on DS1 (class-V F1 82.2 against 84.5) and was not kept.

Nothing here feeds back into detection or HRV. Settings: config.json "ectopic".
"""
import math
import numpy as np
from .core import CONFIG, PT

CFG = CONFIG.get("ectopic", {})
_D = PT.CONFIG["detector"]


def _detrend(w):
    n = w.shape[-1]
    a = w[..., :3].mean(axis=-1, keepdims=True); b = w[..., -3:].mean(axis=-1, keepdims=True)
    return w - (a + (b - a) * np.arange(n) / (n - 1))


def label(r, prem, cfg=None):
    """The label of one beat from its two features (NaN = could not be computed)."""
    cfg = {**CFG, **(cfg or {})}
    if not (r == r and prem == prem):
        return "U"
    if (r < cfg["r_v"] and prem < cfg["prem_v"]) or r < cfg["r_vv"]:
        return "V"
    if r >= cfg["r_n"] and prem < cfg["prem_s"]:
        return "S"
    return "N"


def classify(y, beats, fs, cfg=None):
    """Label every beat. Returns a list of dicts {label, r, prem}, one per beat
    (r and prem are NaN where they could not be computed)."""
    cfg = {**CFG, **(cfg or {})}
    lo, hi, M = int(_D["R_BEFORE_S"] * fs), int(_D["R_AFTER_S"] * fs), int(_D["CORR_LAG"])
    keep, need = _D["POL_KEEP"], _D["POL_MIN"]
    y = np.asarray(y, dtype=float); n = len(y)
    idx = np.arange(-lo, hi + 1)[None, :] + np.arange(-M, M + 1)[:, None]
    tmpl, rr_ref, recent, misses = [], [], [], 0
    out, prev_pos, prev_normal = [], None, False
    for b in beats:
        c = int(round(b["pos"])) if not b["flagged"] else int(b["bp"])
        r = prem = math.nan
        w = y[c + idx] if c - lo - M >= 0 and c + hi + M < n else None
        ok = w is not None and bool(np.all(np.isfinite(w)))
        if prev_pos is not None and rr_ref and not b["gap"]:
            prem = (b["pos"] - prev_pos) / float(np.median(rr_ref))
        lag = 0
        seeding = len(tmpl) < need
        if ok and not seeding:
            t = _detrend(np.median(np.array(tmpl), axis=0)); tc = t - t.mean()
            wd = _detrend(w); wc = wd - wd.mean(axis=1, keepdims=True)
            den = np.sqrt((wc * wc).sum(axis=1) * (tc * tc).sum())
            with np.errstate(divide="ignore", invalid="ignore"):
                rs = np.where(den > 0, (wc * tc).sum(axis=1) / den, -1.0)
            lag = int(np.argmax(rs)) - M; r = float(rs[lag + M])
        normal = False                   # does this beat teach the template and the rhythm?
        if ok:
            if seeding:                  # the first beats the detector could time seed both
                if not b["flagged"]:
                    tmpl.append(w[M]); normal = True
            elif r >= cfg["r_n"] and not (prem < cfg["prem_s"]):
                tmpl.append(w[M + lag]); normal = True; misses = 0
                if len(tmpl) > keep:
                    tmpl.pop(0)
            elif r < cfg["r_n"]:
                misses += 1
            recent.append(w[M]); recent[:] = recent[-keep:]
            if misses >= cfg["reseed"]:  # the normal beat itself has changed
                tmpl = list(recent); misses = 0; rr_ref = []; normal = True
        if prev_pos is not None and not b["gap"] and normal and prev_normal:
            rr_ref.append(b["pos"] - prev_pos); rr_ref[:] = rr_ref[-cfg["rr_keep"]:]
        prev_pos, prev_normal = b["pos"], normal
        out.append(dict(label="U" if seeding or not ok else label(r, prem, cfg), r=r, prem=prem))
    return out


def count(labels):
    """{'V', 'S', 'N', 'U'} counts and the share of beats that could be judged."""
    c = {k: sum(1 for q in labels if q["label"] == k) for k in "VSNU"}
    tot = len(labels)
    c["coverage"] = (tot - c["U"]) / tot if tot else 0.0
    return c
