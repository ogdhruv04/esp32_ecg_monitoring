"""Pulse detection on a PPG signal, pulse intervals and pulse amplitude
(docs/wesad_plan.md, section 4.2).

    y = bandpass(bvp, fs)
    p = detect(y, fs)                 # Pulses: t (s), amp, index
    nn = pulse_intervals(p)           # an NNSeries, cleaned like ECG intervals
    values, info = window_features(p, nn, t0, t1)

Detection is Elgendi et al. 2013 (PLoS ONE 8(10): e76585) with the paper's
windows and offset (config block `ppg`): the band-passed signal is clipped at
zero and squared; a block of interest is where its 111 ms moving average
exceeds its 667 ms moving average plus 2% of the mean squared signal; blocks
shorter than 111 ms are dropped; the systolic peak is the largest sample of the
filtered signal in the block. Ours, and not from the paper: two peaks closer
than 0.3 s are merged keeping the larger, and the pulse time is the parabola
through the peak sample and its two neighbours (64 Hz is 15.6 ms a sample).

Pulse amplitude is the peak minus the lowest filtered sample since the
previous peak. It is in the device's units and has no DC to be divided by, so
it is not a perfusion index: it means something only against the wearer's own
baseline.

The filter is zero-phase and the offset uses the whole recording's mean, so
this is an offline detector. There is no motion gate.
"""
from dataclasses import dataclass
import numpy as np
from scipy import signal as sps
from scipy.ndimage import uniform_filter1d
from .core import CONFIG, NNSeries
from .hrv_time import rmssd, sdnn

P = CONFIG["ppg"]
HR_MIN = CONFIG["session"]["hr_min_intervals"]


@dataclass(frozen=True)
class Pulses:
    t: np.ndarray        # systolic peak time, s, interpolated
    amp: np.ndarray      # peak minus the preceding minimum, signal units
    index: np.ndarray    # peak sample

    def __len__(self):
        return len(self.t)


def bandpass(x, fs):
    sos = sps.butter(P["filter_order"], P["band_hz"], "bandpass", fs=fs, output="sos")
    return sps.sosfiltfilt(sos, np.asarray(x, dtype=float))


def blocks(y, fs):
    """(start, end) sample pairs of Elgendi's blocks of interest, end exclusive."""
    sq = np.clip(y, 0.0, None) ** 2
    ma_peak = uniform_filter1d(sq, max(1, int(round(P["peak_window_s"] * fs))), mode="nearest")
    ma_beat = uniform_filter1d(sq, max(1, int(round(P["beat_window_s"] * fs))), mode="nearest")
    above = ma_peak > ma_beat + P["beat_offset"] * sq.mean()
    edge = np.diff(np.concatenate([[False], above, [False]]).astype(np.int8))
    beg, end = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)
    keep = (end - beg) >= int(round(P["peak_window_s"] * fs))
    return beg[keep], end[keep]


def detect(y, fs):
    """Pulses of a band-passed PPG signal."""
    y = np.asarray(y, dtype=float)
    beg, end = blocks(y, fs)
    min_delay = int(round(P["min_delay_s"] * fs))
    peaks = []
    for b, e in zip(beg, end):
        k = b + int(np.argmax(y[b:e]))
        if peaks and k - peaks[-1] < min_delay:
            if y[k] > y[peaks[-1]]:
                peaks[-1] = k
            continue
        peaks.append(k)
    peaks = np.array(peaks, dtype=int)
    t = np.empty(len(peaks)); amp = np.empty(len(peaks))
    prev = 0
    for i, k in enumerate(peaks):
        d = 0.0
        if 0 < k < len(y) - 1:
            a, b, c = y[k - 1], y[k], y[k + 1]
            den = a - 2 * b + c
            if den < 0:
                d = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
        t[i] = (k + d) / fs
        amp[i] = y[k] - y[prev:k + 1].min()
        prev = k
    return Pulses(t, amp, peaks)


def pulse_intervals(pulses):
    """Pulse-to-pulse intervals as an NNSeries, through the same cleaning as
    ECG intervals (300-2000 ms, the 20% rule)."""
    return NNSeries.from_times(pulses.t)


def apparent_delays(beat_t, pulse_t, max_s=0.6):
    """For each ECG beat, the time to the first pulse peak after it, if within
    max_s; NaN otherwise. Between two separately clocked devices aligned by hand
    this is NOT pulse arrival time (docs/wesad_plan.md, section 2)."""
    beat_t, pulse_t = np.asarray(beat_t, float), np.asarray(pulse_t, float)
    k = np.searchsorted(pulse_t, beat_t, side="right")
    d = np.full(len(beat_t), np.nan)
    ok = k < len(pulse_t)
    d[ok] = pulse_t[k[ok]] - beat_t[ok]
    d[d > max_s] = np.nan
    return d


def match(beat_t, pulse_t, delay_s, tol_s):
    """One-to-one matching of pulses to beats after shifting the pulses back by
    delay_s: (matched, n_beats, n_pulses). Greedy in time order, nearest first."""
    b = np.asarray(beat_t, float)
    p = np.asarray(pulse_t, float) - delay_s
    used = np.zeros(len(p), bool)
    tp = 0
    for t in b:
        k = np.searchsorted(p, t)
        best, bd = -1, tol_s
        for j in (k - 1, k):
            if 0 <= j < len(p) and not used[j] and abs(p[j] - t) <= bd:
                best, bd = j, abs(p[j] - t)
        if best >= 0:
            used[best] = True; tp += 1
    return tp, len(b), len(p)


def window_features(pulses, nn, t0, t1):
    """The plan's four wrist-BVP features of one window: (values, info). A
    withheld feature is NaN; info says how much data the window held."""
    k = np.flatnonzero((pulses.t >= t0) & (pulses.t < t1))
    w = nn.window(t0, t1)
    acc = w.accepted
    out = dict(pr=np.nan, ln_rmssd_p=np.nan, ln_sdnn_p=np.nan, ln_amp=np.nan)
    info = dict(pulses=len(k), accepted=int(acc.sum()), coverage=w.coverage, valid_s=w.valid_s)
    if acc.sum() >= HR_MIN:
        out["pr"] = 60000.0 / float(np.median(w.values))
    r, s = rmssd(w), sdnn(w)
    if r.ok and r.value > 0:
        out["ln_rmssd_p"] = float(np.log(r.value))
    if s.ok and s.value > 0:
        out["ln_sdnn_p"] = float(np.log(s.value))
    if len(k) > 1:
        a = pulses.amp[k[1:]][acc]           # pulses that end an accepted interval
        a = a[a > 0]
        if len(a) >= P["min_pulses"]:
            out["ln_amp"] = float(np.log(np.median(a)))
    return out, info
