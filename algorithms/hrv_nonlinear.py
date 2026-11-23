"""Non-linear HRV: Poincare SD1/SD2, DFA alpha1, sample entropy.

None of them crosses a hole in the NN series:

  SD1, SD2   from the pairs (NN[n], NN[n+1]) of SUCCESSIVE accepted intervals,
             rotated 45 degrees (Brennan et al. 2001):
             SD1 = sd((NN[n] - NN[n+1]) / sqrt 2), SD2 = sd((NN[n] + NN[n+1]) / sqrt 2)
  DFA alpha1 detrended fluctuation analysis (Peng et al. 1995): profile =
             cumulative sum of NN - mean; non-overlapping boxes of n beats laid
             from the start of each run of consecutive accepted intervals, so
             no box spans a hole; a line is fitted in each box; F(n) = rms
             residual over all boxes; alpha1 = slope of log F(n) on log n over
             n = 4 .. 16, the range Peng et al. define alpha1 on ("a least
             squares fit of log F(n) vs log n for 4 <= n <= 16", Chaos
             1995;5:82-87, p. 85). neurokit2 uses 4-11 and gives a different
             number (docs/hrv_minimum_windows.md). Only runs at least 16 long
             are used, so every box size sees the same data.
  SampEn     Richman & Moorman 2000, m = 2, r = 0.2 x sd of the accepted
             intervals: -ln(A / B), B = pairs of length-2 templates within r
             (Chebyshev distance, self-matches excluded), A = the same for
             length 3. A template is three consecutive accepted intervals from
             one run; pairs are counted across all templates.
"""
import math
import numpy as np
from .core import HRV, gate, minimum, result

SCALE_MIN, SCALE_MAX = HRV["dfa"]["scale_min"], HRV["dfa"]["scale_max"]
SAMPEN_M, SAMPEN_R = HRV["sampen"]["m"], HRV["sampen"]["r_sd"]


# ------------------------------------------------------------------ Poincare
def poincare(nn):
    """{'sd1', 'sd2'} -> Result."""
    a, b = nn.pairs()
    out = {}
    for key, name, x in (("sd1", "SD1", (a - b) / math.sqrt(2.0)),
                         ("sd2", "SD2", (a + b) / math.sqrt(2.0))):
        why = gate(nn, key)
        if why is None and len(a) < minimum(key)["pairs"]:
            why = f"{len(a)} successive pairs, needs {minimum(key)['pairs']}"
        out[key] = result(nn, name, "ms", None if why else float(np.std(x, ddof=1)), why, len(a))
    return out


# ----------------------------------------------------------------------- DFA
def dfa_fluctuations(runs, scales, mean):
    """F(n) for each box size n over runs of consecutive intervals."""
    out = []
    for n in scales:
        x = np.arange(n, dtype=float)
        xc = x - x.mean(); sxx = float((xc * xc).sum())
        ss, boxes = 0.0, 0
        for r in runs:
            k = len(r) // n
            if k == 0:
                continue
            y = np.cumsum(r - mean)[:k * n].reshape(k, n)
            yc = y - y.mean(axis=1, keepdims=True)
            slope = (yc * xc).sum(axis=1) / sxx
            res = yc - slope[:, None] * xc
            ss += float((res * res).mean(axis=1).sum()); boxes += k
        out.append(math.sqrt(ss / boxes) if boxes else math.nan)
    return np.array(out)


def dfa_alpha1_raw(runs):
    """alpha1 of runs of consecutive intervals (each at least SCALE_MAX long),
    with no minimum-window check; NaN when F(n) is zero at some box size."""
    scales = np.arange(SCALE_MIN, SCALE_MAX + 1)
    f = dfa_fluctuations(runs, scales, float(np.mean(np.concatenate(runs))))
    if not np.all(f > 0):
        return math.nan
    return float(np.polyfit(np.log(scales), np.log(f), 1)[0])


def dfa_alpha1(nn):
    runs = nn.runs(min_len=SCALE_MAX)
    n_used = int(sum(len(r) for r in runs))
    why = gate(nn, "dfa_alpha1")
    need = minimum("dfa_alpha1")["nn_in_runs"]
    if why is None and n_used < need:
        why = f"{n_used} NN intervals in runs of {SCALE_MAX} or more, needs {need}"
    if why:
        return result(nn, "DFA alpha1", "", withheld=why, n_used=n_used)
    alpha = dfa_alpha1_raw(runs)
    if alpha != alpha:
        return result(nn, "DFA alpha1", "", withheld="no fluctuation at some box size", n_used=n_used)
    return result(nn, "DFA alpha1", "", alpha, n_used=n_used)


# ------------------------------------------------------------ sample entropy
def _matches(templates, r):
    """Pairs (i < j) of rows within Chebyshev distance r."""
    n = len(templates)
    count = 0
    for i in range(n - 1):
        d = np.max(np.abs(templates[i + 1:] - templates[i]), axis=1)
        count += int(np.count_nonzero(d <= r))
    return count


def sample_entropy_raw(runs, sd):
    """SampEn of runs of consecutive intervals (each at least m + 1 long) with
    r = SAMPEN_R * sd, no minimum-window check. Returns (value or NaN, number
    of templates)."""
    m = SAMPEN_M
    long_t = np.concatenate([np.lib.stride_tricks.sliding_window_view(r, m + 1) for r in runs])
    r = SAMPEN_R * sd
    b = _matches(long_t[:, :m], r)      # the length-m template at the same place
    a = _matches(long_t, r)
    return (-math.log(a / b) if a and b else math.nan), len(long_t)


def sample_entropy(nn):
    m = SAMPEN_M
    runs = nn.runs(min_len=m + 1)
    n_t = int(sum(len(r) - m for r in runs))
    why = gate(nn, "sampen")
    need = minimum("sampen")["templates"]
    if why is None and n_t < need:
        why = f"{n_t} templates of {m + 1} consecutive NN intervals, needs {need}"
    if why:
        return result(nn, "SampEn", "", withheld=why, n_used=n_t)
    sd = float(np.std(nn.values, ddof=1))
    v, _ = sample_entropy_raw(runs, sd)
    if v != v:
        return result(nn, "SampEn", "", withheld="no template matches within r", n_used=n_t)
    return result(nn, "SampEn", "", v, n_used=n_t, r_ms=SAMPEN_R * sd)


def nonlinear(nn):
    out = poincare(nn)
    out["dfa_alpha1"] = dfa_alpha1(nn)
    out["sampen"] = sample_entropy(nn)
    return out
