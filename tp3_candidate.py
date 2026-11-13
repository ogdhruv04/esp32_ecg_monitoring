"""Candidate timing point 3 (tp3): a polarity-free beat position. NOT SHIPPED.

tp2.1 times a beat at the peak of its dominant QRS deflection, and for that it
must first decide the beat's polarity from the median of the previous beats.
When the two lobes of the QRS are of similar size (ratio under POL_RATIO 1.5)
it cannot decide, flags every beat, and the recording has no HRV at all. That
is the biphasic-QRS coverage collapse (CLAUDE.md).

tp3 never asks which lobe is the R wave. It slides the beat's window against
the median beat and takes the lag at which the two correlate best:

    position = d + lag* ,  lag* = argmax over |lag| <= LAG of
               corr( detrend(x[d + lag - lo : d + lag + hi]),  median beat )

with parabolic interpolation of the correlation around its maximum, d being
the detector's 5-15 Hz peak. tp2.1 already computes this lag for its per-beat
check; here it is the measurement.

REF says what the position refers to.
  "anchor"  position = d + lag*: where the beat sits relative to the median
            beat's window. The window's place on the QRS is arbitrary and, as
            aligned windows keep joining the template, it wanders by a few ms
            over minutes. RR intervals of neighbouring beats do not see that;
            absolute times do.
  "peak"    position = d + lag* + (p - lo), p being the place of one peak of
            the median beat: its largest deflection of either sign when the
            template is first formed, then FOLLOWED from template to template
            (the nearest peak of the same sign within TRACK samples), not
            chosen again. So the time refers to a fixed feature of the QRS,
            the wander of the window cancels, and no beat-by-beat decision
            about polarity is made. If the followed peak disappears the
            largest deflection is picked afresh and that one beat is flagged.

A beat is flagged (position falls back to the 5-15 Hz peak, kept out of HRV)
when the median beat is not ready (fewer than POL_MIN beats), its window holds
a gap, the best correlation is below R_MIN, or the best lag is at the end of
the search range (no maximum inside it).

ALIGN: the median beat is built from the previous beats' windows. With
ALIGN = True each window joins the template at its own best lag, so the
template stays sharp; with False it joins anchored on the 5-15 Hz peak, as
tp2.1's template does, and a peak that jumps between lobes blurs it.

retime() works from the detector's finished beats, offline. It uses nothing
later than d + hi + LAG samples and nothing older than the detector's history,
and beats are processed in the order they were detected, so a streaming
version would give the same positions at the cost of waiting LAG samples
longer per beat. Detection is not touched: same beats, same 5-15 Hz peaks.
"""
import json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pan_tompkins as PT

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tp3_candidate.json")
CONFIG = json.load(open(_PATH)) if os.path.exists(_PATH) else None
DEFAULT = {"LAG": 10, "R_MIN": 0.5, "ALIGN": True, "REF": "peak", "TRACK": 2}
_D = PT.CONFIG["detector"]


def _detrend_rows(w):
    """PT._detrend on every row: subtract the line through the means of the
    first and last 3 samples."""
    n = w.shape[-1]
    a = w[..., :3].mean(axis=-1, keepdims=True)
    b = w[..., -3:].mean(axis=-1, keepdims=True)
    return w - (a + (b - a) * np.arange(n) / (n - 1))


def retime(y, beats, fs, cfg=None):
    """tp3 positions for the detector's beats. Returns a new list of beat
    dicts (pos, flagged replaced; bp, kind, gap kept) with 'r', 'lag' and, for a
    flagged beat, 'why'."""
    cfg = {**DEFAULT, **(CONFIG["timing"] if CONFIG else {}), **(cfg or {})}
    LAG, R_MIN, ALIGN = int(cfg["LAG"]), float(cfg["R_MIN"]), bool(cfg["ALIGN"])
    REF, TRACK = cfg["REF"], int(cfg["TRACK"])
    ref_k, ref_sign = None, 0.0          # the followed peak of the median beat
    lo, hi = int(_D["R_BEFORE_S"] * fs), int(_D["R_AFTER_S"] * fs)
    keep, need = _D["POL_KEEP"], _D["POL_MIN"]
    y = np.asarray(y, dtype=float)
    n = len(y)
    idx = np.arange(-lo, hi + 1)[None, :] + np.arange(-LAG, LAG + 1)[:, None]
    segs, out = [], []
    for b in beats:
        d = int(b["bp"])
        nb = dict(b)
        # the fallback position is the detector's own (5-15 Hz peak, tp2.1's fallback)
        fallback = b["pos"] if b["flagged"] else None
        inside = d - lo - LAG >= 0 and d + hi + LAG < n
        w = y[d + idx] if inside else None
        pos, flagged, r_best, lag = None, True, math.nan, 0
        why = "window outside the signal" if w is None else ("median beat not ready" if len(segs) < need else "gap in the window")
        if w is not None and len(segs) >= need and np.all(np.isfinite(w)):
            t = _detrend_rows(np.median(np.array(segs), axis=0))
            repicked = False
            ref = float(lo)
            if REF == "peak":
                L = len(t)
                k = None
                if ref_k is not None:
                    a0, a1 = max(1, ref_k - TRACK), min(L - 2, ref_k + TRACK)
                    kk = a0 + int(np.argmax(ref_sign * t[a0:a1 + 1]))
                    v = ref_sign * t
                    if v[kk] > 0 and v[kk] >= v[kk - 1] and v[kk] >= v[kk + 1]:
                        k = kk
                if k is None:
                    repicked = ref_k is not None
                    k = int(np.argmax(np.abs(t)))
                    ref_sign = 1.0 if t[k] >= 0 else -1.0
                ref_k = k
                v = ref_sign * t
                ref = k + (PT._parabolic(v[k - 1], v[k], v[k + 1]) if 0 < k < L - 1 else 0.0)
            wd = _detrend_rows(w)
            tc = t - t.mean(); wc = wd - wd.mean(axis=1, keepdims=True)
            den = np.sqrt((wc * wc).sum(axis=1) * (tc * tc).sum())
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(den > 0, (wc * tc).sum(axis=1) / den, np.nan)
            if np.all(np.isfinite(r)):
                k = int(np.argmax(r))
                r_best = float(r[k])
                why = "correlation under R_MIN" if r_best < R_MIN else "best lag at the end of the range"
                if r_best >= R_MIN and 0 < k < 2 * LAG:
                    lag = k - LAG
                    pos = d + lag + PT._parabolic(r[k - 1], r[k], r[k + 1]) + (ref - lo)
                    flagged = repicked
                    why = "followed peak picked again" if repicked else None
        if flagged:
            pos = fallback if fallback is not None else _fallback(y, d, fs)
        # the window joins the template after it has been timed
        if w is not None:
            seg = w[LAG + (lag if ALIGN else 0)]
            if np.all(np.isfinite(seg)):
                segs.append(seg)
                if len(segs) > keep:
                    segs.pop(0)
        nb.update(pos=float(pos), flagged=bool(flagged), r=r_best, lag=lag, why=why if flagged else None)
        out.append(nb)
    return out


def _fallback(y, d, fs):
    """The 5-15 Hz peak with parabolic interpolation, as tp2.1 falls back to.
    The detector does not keep its bandpassed signal, so it is recomputed over
    a short stretch around d."""
    from scipy import signal as sps
    i0, i1 = max(0, d - int(2 * fs)), min(len(y), d + 3)
    seg = np.nan_to_num(y[i0:i1])
    for kind, f0 in (("hp", 5.0), ("lp", 15.0)):
        q = PT._rbj(kind, f0, 0.7071, fs)
        seg = sps.lfilter(q.b, (1.0,) + q.a, seg)
    bp = np.abs(seg); k = d - i0
    if 1 <= k < len(bp) - 1:
        return d + PT._parabolic(bp[k - 1], bp[k], bp[k + 1])
    return float(d)
