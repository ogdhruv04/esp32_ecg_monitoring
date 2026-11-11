"""Frequency-domain HRV: LF and HF power from a Lomb-Scargle periodogram.

The NN series is sampled once per beat, unevenly, and has holes where beats
were rejected. Lomb-Scargle works on exactly that, so nothing is interpolated
and no hole is filled.

  P(f)    classic periodogram (Lomb 1976, Scargle 1982) of the mean-removed
          accepted intervals at their beat times
  PSD(f)  2 * P(f) * T / N   in ms^2/Hz, T = first to last accepted beat,
          N = accepted intervals. Scaled so that a sinusoid of amplitude A
          contributes A^2/2 to the band it sits in, like a one-sided PSD.
  LF, HF  trapezoid integral of the PSD over 0.04-0.15 Hz and 0.15-0.40 Hz on
          a grid of step 1/(oversample * T) that includes both band edges
  LF/HF, LFnu = 100 * LF / (LF + HF)

HF and everything using it are withheld when the mean beat rate is below twice
the top of the HF band (mean NN above 1250 ms): beats cannot sample 0.4 Hz then.

Holes are not free. Each missing interval spreads some of the series' variance
across all frequencies, which lifts both bands and the smaller one most. With
5% of beats flagged at random (coverage 90%) HF read 16-30% high in simulation
(analysis/hrv_min_window_simulation.txt, part 2), so LF and HF are withheld
below 95% coverage. neurokit2's Lomb-Scargle has the same floor: agreeing with
it says the arithmetic is the same, not that the floor is absent.
"""
import math
import numpy as np
from .core import HRV, gate, result

BANDS = HRV["bands_hz"]
OVERSAMPLE = HRV["lomb_oversample"]


def lomb_scargle(t, y, freqs):
    """Classic Lomb-Scargle periodogram of y(t) at freqs (Hz, > 0). y must
    already be mean-removed. Same quantity as scipy.signal.lombscargle
    (unnormalised) and astropy's normalization='psd' with fit_mean=False."""
    t = np.asarray(t, dtype=float); y = np.asarray(y, dtype=float)
    w = 2.0 * np.pi * np.asarray(freqs, dtype=float)[:, None]
    tt = (t - t[0])[None, :]
    tau = np.arctan2(np.sin(2 * w * tt).sum(1), np.cos(2 * w * tt).sum(1))[:, None] / (2 * w)
    c = np.cos(w * (tt - tau)); s = np.sin(w * (tt - tau))
    cc = (c * c).sum(1); ss = (s * s).sum(1)
    yc = (y[None, :] * c).sum(1); ys = (y[None, :] * s).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = 0.5 * (np.where(cc > 0, yc * yc / cc, 0.0) + np.where(ss > 0, ys * ys / ss, 0.0))
    return p


def band_grid(lo, hi, span_s, oversample=OVERSAMPLE):
    """Frequencies from lo to hi inclusive, step no larger than 1/(oversample*span)."""
    n = int(math.ceil((hi - lo) * oversample * span_s)) + 1
    return np.linspace(lo, hi, max(n, 2))


def band_power(t, v, band):
    """Integral of the PSD (ms^2/Hz) over one band; t in s, v in ms."""
    span = float(t[-1] - t[0])
    f = band_grid(band[0], band[1], span)
    psd = 2.0 * lomb_scargle(t, v - np.mean(v), f) * span / len(v)
    return float(np.trapezoid(psd, f))


def frequency_domain(nn):
    """{'lf', 'hf', 'lf_hf', 'lf_nu'} -> Result."""
    t, v = nn.times, nn.values
    n = len(v)
    why_lf, why_hf = gate(nn, "lf"), gate(nn, "hf")
    if why_hf is None and n and float(np.mean(v)) / 1000.0 > 1.0 / (2.0 * BANDS["hf"][1]):
        why_hf = (f"mean NN {np.mean(v):.0f} ms: beat rate below twice the "
                  f"{BANDS['hf'][1]:g} Hz band edge")
    lf = None if why_lf else band_power(t, v, BANDS["lf"])
    hf = None if why_hf else band_power(t, v, BANDS["hf"])
    out = {"lf": result(nn, "LF", "ms^2", lf, why_lf, n),
           "hf": result(nn, "HF", "ms^2", hf, why_hf, n)}
    why = why_lf or why_hf
    if why is None and not (lf > 0.0 and hf > 0.0):
        why = "no power in a band"
    out["lf_hf"] = result(nn, "LF/HF", "", None if why else lf / hf, why, n)
    out["lf_nu"] = result(nn, "LFnu", "%", None if why else 100.0 * lf / (lf + hf), why, n)
    return out
