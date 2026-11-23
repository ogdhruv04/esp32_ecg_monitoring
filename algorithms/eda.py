"""Skin conductance: tonic and phasic components and the count of skin
conductance responses (docs/wesad_plan.md, section 4.3).

    x4 = to_rate(x, fs)                        # anything -> 4 Hz
    d = decompose(x4)                          # Decomposition: tonic, phasic (uS), peaks
    values = window_features(x4, d, t0, t1)

The decomposition is cvxEDA (Greco, Valenza, Lanata, Scilingo, Citi, IEEE Trans
Biomed Eng 2016;63(4):797-804) with the published defaults (config block `eda`),
solved by neurokit2's copy of the reference code with cvxopt. The input is the
whole recording, standardised as the reference implementation's example does;
the components are converted back to microsiemens. It is an offline method.

A skin conductance response is a local maximum of the phasic component at
least scr_min_us high and prominent, at least scr_min_separation_s after the
previous one.
"""
from dataclasses import dataclass
from fractions import Fraction
import numpy as np
from scipy import signal as sps
from .core import CONFIG

E = CONFIG["eda"]
FS = E["fs_hz"]


def to_rate(x, fs_in, fs_out=FS):
    """Polyphase resampling with the ends extended by a line, so a signal that
    sits far from zero has no edge transient."""
    x = np.asarray(x, dtype=float)
    if fs_in == fs_out:
        return x
    r = Fraction(fs_out / fs_in).limit_denominator(10000)
    return sps.resample_poly(x, r.numerator, r.denominator, padtype="line")


@dataclass(frozen=True)
class Decomposition:
    tonic: np.ndarray        # uS
    phasic: np.ndarray       # uS; its driver is non-negative, the component itself can dip slightly below 0
    peaks: np.ndarray        # sample indices of the skin conductance responses
    fs: float


def cvxeda(z, fs):
    """(tonic, phasic) of a standardised signal. Separate so that tests can
    reach the solver directly."""
    from neurokit2.eda.eda_phasic import _eda_phasic_cvxeda
    return _eda_phasic_cvxeda(np.asarray(z, dtype=float), sampling_rate=fs, tau0=E["tau0"], tau1=E["tau1"],
                              delta_knot=E["delta_knot_s"], alpha=E["alpha"], gamma=E["gamma"])


def scr_peaks(phasic, fs=FS, min_us=None):
    thr = E["scr_min_us"] if min_us is None else min_us
    k, _ = sps.find_peaks(phasic, height=thr, prominence=thr,
                          distance=max(1, int(round(E["scr_min_separation_s"] * fs))))
    return k


def decompose(x_us, fs=FS, min_us=None):
    x = np.asarray(x_us, dtype=float)
    if not np.all(np.isfinite(x)):
        raise ValueError("decompose needs finite samples")
    m, s = float(x.mean()), float(x.std())
    if s == 0:
        return Decomposition(x.copy(), np.zeros(len(x)), np.zeros(0, dtype=int), fs)
    tonic, phasic = cvxeda((x - m) / s, fs)
    phasic = phasic * s
    return Decomposition(tonic * s + m, phasic, scr_peaks(phasic, fs, min_us), fs)


def window_features(x_us, d, t0, t1):
    """The plan's four EDA features of one window. All NaN when any raw sample
    of the window is at or below zero or not finite (no skin contact)."""
    i0, i1 = int(np.ceil(t0 * d.fs - 1e-9)), int(np.ceil(t1 * d.fs - 1e-9))
    out = dict(scl=np.nan, scl_slope=np.nan, scr_rate=np.nan, phasic_mean=np.nan)
    raw = np.asarray(x_us[i0:i1], dtype=float)
    if i0 < 0 or i1 > len(d.tonic) or len(raw) < 2 or not np.all(np.isfinite(raw)) or np.any(raw <= 0):
        return out
    minutes = np.arange(i1 - i0) / d.fs / 60.0
    out["scl"] = float(d.tonic[i0:i1].mean())
    out["scl_slope"] = float(np.polyfit(minutes, d.tonic[i0:i1], 1)[0])
    out["scr_rate"] = float(np.sum((d.peaks >= i0) & (d.peaks < i1)) / ((t1 - t0) / 60.0))
    out["phasic_mean"] = float(d.phasic[i0:i1].mean())
    return out
