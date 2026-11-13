"""Reference implementation of the app's Session report (Session.kt).

Everything measured comes from the algorithms/ package and pan_tompkins.py.
This module only decides WHICH beats and samples belong to a session and how
two session-level numbers (heart rate, breathing rate) are summarised; those
rules are in session_config.json. SessionParityTest checks that the phone
gives the same report as this on the fixtures make_session_fixtures.py writes.

A session covers the absolute sample indices [s0, s1):
  - beats: every beat the detector located by the time it had processed
    sample s1 + tail - 1, whose position lies in [s0, s1)
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

# Session-level rules. They belong in algorithms/config.json ("session"),
# which the algorithms workstream has not written yet; until it does, these
# PROVISIONAL values apply and every reason they produce says so. They were
# set by hand, not tuned: 30 intervals is MIN_BEATS_FOR_HRV (tp2_config.json),
# 5 windows and a 4 breaths/min spread were chosen in review on 12 Nov 2026.
PROVISIONAL = {"hr_min_intervals": 30, "breathing_min_windows": 5, "breathing_max_range_bpm": 4.0}
RULES = A.CONFIG.get("session", PROVISIONAL)
RULES_PROVISIONAL = "session" not in A.CONFIG
TAG = " (provisional rule)" if RULES_PROVISIONAL else ""
BR_STEP_S = A.CONFIG["bidmc"]["step_s"]         # windows as in the BIDMC validation

# The measures on the report, in order. The standard (3-minute) report leaves
# out DFA alpha1 and sample entropy, which need more data than it can hold;
# the extended (5-minute) one adds them. LFnu was not asked for.
HRV_KEYS = ["rmssd", "sdnn", "pnn50", "sd1", "sd2", "lf", "hf", "lf_hf"]
KEYS = ["hr", "br"] + HRV_KEYS


def keys(kind):
    return KEYS + SESSION["kinds"][kind]["extra_keys"]


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
    need = RULES["hr_min_intervals"]
    if len(rr) < need:
        return Result("HR", None, "bpm", f"{len(rr)} beat-to-beat intervals, needs {need}{TAG}",
                      len(rr), span, span, cov)
    return Result("HR", 60000.0 / float(np.median(rr)), "bpm", None, len(rr), span, span, cov)


def breathing_windows(mods, t0, t1):
    """Fused breathing rate of every 32 s window starting every step s in [t0, t1)."""
    W, step = A.CONFIG["breathing"]["window_s"], BR_STEP_S
    out, k = [], 0
    while k * step <= (t1 - t0) - W + 1e-9:
        w0 = t0 + k * step
        out.append((w0, A.breathing_rate(mods, w0, w0 + W)["fused"]))
        k += 1
    return out


def breathing(windows, span_s):
    rates = [r.value for _, r in windows if r.ok]
    need, spread = RULES["breathing_min_windows"], RULES["breathing_max_range_bpm"]
    m = len(windows)
    cov = len(rates) / m if m else 0.0
    extra = {"min": float(min(rates)), "max": float(max(rates)), "windows": m} if rates else {"windows": m}
    if len(rates) < need:
        why = (f"{len(rates)} of {m} breathing windows gave a rate, needs {need}{TAG}" if m
               else "session shorter than one breathing window")
        return Result("Breathing rate", None, "breaths/min", why, len(rates), span_s, span_s, cov, extra)
    # Windows that disagree by more than `spread` are not one breathing rate.
    if max(rates) - min(rates) > spread:
        why = (f"window rates span {min(rates):.1f}\u2013{max(rates):.1f} breaths/min, "
               f"more than {spread:g}{TAG}")
        return Result("Breathing rate", None, "breaths/min", why, len(rates), span_s, span_s, cov, extra)
    return Result("Breathing rate", float(np.median(rates)), "breaths/min", None, len(rates), span_s, span_s, cov, extra)


def session_report(pt, y, s0, s1, fs=256.0, kind="standard"):
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
    rep.update({k: h[k] for k in keys(kind)[2:]})
    rep["_windows"] = wins
    rep["_beats"] = beats
    rep["_nn"] = nn
    return rep


# ------------------------------------------------------------ guided breathing
LIVE = SESSION["guided_breathing"]


def live_window(pt, y, n, fs=256.0):
    """The guided-breathing screen's numbers once the detector has processed
    absolute samples [0, n): RMSSD over the last rmssd_window_s and the fused
    breathing rate over the last breathing window, from the beats located so
    far (LiveHrv.kt is the port)."""
    t1 = n / fs
    w_rm = LIVE["rmssd_window_s"]
    beats_rm = [b for b in pt.beats if t1 - w_rm <= b["pos"] / fs < t1]
    nn = NNSeries.from_beats(beats_rm, fs)
    W = A.CONFIG["breathing"]["window_s"]
    n0 = n - int(W * fs)
    ys = np.full(n, np.nan)
    ys[max(n0, 0):n] = y[max(n0, 0):n]
    beats_br = [b for b in pt.beats if t1 - W <= b["pos"] / fs < t1]
    mods = A.modulations(ys, beats_br, fs)
    return {"rmssd": A.rmssd(nn), "br": A.breathing_rate(mods, t1 - W, t1)["fused"]}
