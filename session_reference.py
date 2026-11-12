"""Reference implementation of the app's Session report (Session.kt).

Everything measured comes from the algorithms/ package and pan_tompkins.py.
This module only decides WHICH beats and samples belong to a session and how
two session-level numbers (heart rate, breathing rate) are summarised; those
rules are in session_config.json. SessionParityTest checks that the phone
gives the same report as this on the fixtures make_session_fixtures.py writes.

A session covers the absolute sample indices [s0, s1):
  - beats: every beat the detector located by the time it had processed
    sample s1 + tail - 1, whose tp2.1 position lies in [s0, s1)
  - samples: the filtered signal inside [s0, s1) only; a lost sample is NaN
  - the NN series is built from those beats alone (NNSeries.from_beats), so
    its cleaning is seeded from the session's own first intervals
"""
import json, math, os, sys
import numpy as np

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import algorithms as A
from algorithms import NNSeries, Result

with open(os.path.join(_ROOT, "session_config.json")) as _f:
    SESSION = json.load(_f)
VERSION = SESSION["version"]

# The measures on the report, in order. LFnu and sample entropy are left out:
# LFnu was not asked for, and SampEn needs 180 s of valid NN time, which a
# 180 s session can never hold.
HRV_KEYS = ["rmssd", "sdnn", "pnn50", "sd1", "sd2", "lf", "hf", "lf_hf", "dfa_alpha1"]
KEYS = ["hr", "br"] + HRV_KEYS


def run_detector(values, skips, end):
    """Feed float32 filtered samples (skip_before[i] lost samples before row i)
    to a fresh detector, stopping once the absolute index reaches `end`.
    Returns (detector, filtered signal by absolute index with NaN where lost)."""
    pt = A.core.PT.PanTompkins(256.0)
    y = []
    n = 0
    for v, s in zip(values, skips):
        if s:
            pt.skip(int(s)); y.extend([math.nan] * int(s)); n += int(s)
            if n >= end:
                break
        pt.process(float(v)); y.append(float(v)); n += 1
        if n >= end:
            break
    return pt, np.array(y, dtype=float)


def heart_rate(beats, fs):
    pos = [b["pos"] for b in beats]
    rr = [1000.0 * (pos[i] - pos[i - 1]) / fs for i in range(1, len(beats)) if not beats[i]["gap"]]
    n_all = max(len(beats) - 1, 0)
    cov = len(rr) / n_all if n_all else 0.0
    span = (pos[-1] - pos[0]) / fs if len(pos) > 1 else 0.0
    need = SESSION["hr_min_intervals"]
    if len(rr) < need:
        return Result("HR", None, "bpm", f"{len(rr)} beat-to-beat intervals, needs {need}",
                      len(rr), span, span, cov)
    return Result("HR", 60000.0 / float(np.median(rr)), "bpm", None, len(rr), span, span, cov)


def breathing_windows(mods, t0, t1):
    """Fused breathing rate of every 32 s window starting every step s in [t0, t1)."""
    W, step = A.CONFIG["breathing"]["window_s"], SESSION["breathing_step_s"]
    out, k = [], 0
    while k * step <= (t1 - t0) - W + 1e-9:
        w0 = t0 + k * step
        out.append((w0, A.breathing_rate(mods, w0, w0 + W)["fused"]))
        k += 1
    return out


def breathing(windows, span_s):
    rates = [r.value for _, r in windows if r.ok]
    need = SESSION["breathing_min_windows"]
    m = len(windows)
    cov = len(rates) / m if m else 0.0
    if len(rates) < need:
        why = (f"{len(rates)} of {m} breathing windows gave a rate, needs {need}" if m
               else "session shorter than one breathing window")
        return Result("Breathing rate", None, "breaths/min", why, len(rates), span_s, span_s, cov)
    return Result("Breathing rate", float(np.median(rates)), "breaths/min", None, len(rates), span_s, span_s, cov,
                  {"min": float(min(rates)), "max": float(max(rates)), "windows": m})


def session_report(pt, y, s0, s1, fs=256.0):
    """{key: Result} for the session [s0, s1), plus the per-window breathing
    results under '_windows' and the session's beats under '_beats'."""
    beats = [b for b in pt.beats if s0 <= b["pos"] < s1]
    nn = NNSeries.from_beats(beats, fs)
    h = A.hrv(nn)
    ys = np.full(max(len(y), s1), np.nan)
    ys[s0:min(s1, len(y))] = y[s0:min(s1, len(y))]
    mods = A.modulations(ys, beats, fs)
    wins = breathing_windows(mods, s0 / fs, s1 / fs)
    rep = {"hr": heart_rate(beats, fs), "br": breathing(wins, (s1 - s0) / fs)}
    rep.update({k: h[k] for k in HRV_KEYS})
    rep["_windows"] = wins
    rep["_beats"] = beats
    rep["_nn"] = nn
    return rep
