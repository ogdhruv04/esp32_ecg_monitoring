"""Shared types for the algorithms package: the NN series, the result type and
the minimum-window gate.

An NN series here is ONE entry per inter-beat interval, NaN where the interval
is not usable (a flagged or searched-back beat at either end, lost samples in
between, outside 300-2000 ms, or dropped by the 20% rule). That is the phone's
rrHist and pan_tompkins.rr_history / clean_nn, without the 256-entry depth
limit. Keeping the unusable entries is what makes two things well defined:

  coverage  accepted intervals / all inter-beat intervals in the window
  adjacency two accepted intervals are successive only when they are
            neighbouring entries, so no measure differences across a hole

Every measure returns a Result. Its value is None when the window is shorter
than the measure's minimum (config.json, docs/hrv_minimum_windows.md) or the
measure is undefined on this data; `withheld` then says why. A value is never
computed from too little data and left for the caller to judge.
"""
import json, math, os, sys
from dataclasses import dataclass, field
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:                      # pan_tompkins.py lives at the repo root
    sys.path.insert(0, _ROOT)
import pan_tompkins as PT

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as _f:
    CONFIG = json.load(_f)
VERSION = CONFIG["version"]
HRV = CONFIG["hrv"]
MIN_WINDOW = HRV["min_window"]


@dataclass(frozen=True)
class Result:
    name: str
    value: float | None          # None = withheld
    unit: str
    withheld: str | None         # why, when value is None
    n_used: int                  # data points the value rests on (NN, pairs, templates ...)
    valid_s: float               # summed duration of the accepted NN intervals
    span_s: float                # first to last beat of the window
    coverage: float              # accepted / all inter-beat intervals in the window
    extra: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.value is not None

    def __str__(self):
        v = f"{self.value:.4g} {self.unit}".strip() if self.ok else f"withheld ({self.withheld})"
        return f"{self.name}: {v} [{self.valid_s:.0f} s valid, coverage {100*self.coverage:.0f}%]"


@dataclass(frozen=True)
class NNSeries:
    beat_t: np.ndarray           # (n+1,) beat times, s
    nn_ms: np.ndarray            # (n,) interval ending at beat_t[i+1], ms; NaN = not usable

    # ------------------------------------------------------------ builders
    @classmethod
    def from_beats(cls, beats, fs):
        """From PanTompkins.beats (tp2.1 positions, flags, kinds, gaps), cleaned
        by the detector's own rules."""
        t = np.array([b["pos"] for b in beats], dtype=float) / fs
        rr = PT.rr_history(beats, fs, depth=len(beats) + 1)
        return cls._cleaned(t, rr)

    @classmethod
    def from_times(cls, beat_t, flagged=None, clean=True):
        """From beat times in seconds. An interval with a flagged beat at either
        end is unusable. clean=True applies pan_tompkins.clean_nn."""
        t = np.asarray(beat_t, dtype=float)
        rr = 1000.0 * np.diff(t)
        if flagged is not None:
            f = np.asarray(flagged, dtype=bool)
            rr[f[:-1] | f[1:]] = np.nan
        return cls._cleaned(t, list(rr)) if clean else cls(t, rr)

    @classmethod
    def from_intervals(cls, nn_ms, clean=False):
        """From a gap-free list of intervals in ms (tests, simulations)."""
        nn = np.asarray(nn_ms, dtype=float)
        if not np.all(np.isfinite(nn)):
            raise ValueError("from_intervals needs finite intervals; use from_times for gaps")
        t = np.concatenate([[0.0], np.cumsum(nn) / 1000.0])
        return cls._cleaned(t, list(nn)) if clean else cls(t, nn)

    @classmethod
    def _cleaned(cls, t, rr):
        if len(t) < 2:
            return cls(np.asarray(t, dtype=float), np.zeros(0))
        acc, _ = PT.clean_nn(list(rr))
        return cls(np.asarray(t, dtype=float), np.where(acc, np.asarray(rr, dtype=float), np.nan))

    # ------------------------------------------------------------- windows
    def window(self, t0, t1):
        """The intervals whose two beats both lie in [t0, t1)."""
        k = np.flatnonzero((self.beat_t >= t0) & (self.beat_t < t1))
        if len(k) < 2:
            return NNSeries(self.beat_t[k], np.zeros(0))
        return NNSeries(self.beat_t[k[0]:k[-1] + 1], self.nn_ms[k[0]:k[-1]])

    # ---------------------------------------------------------- properties
    @property
    def accepted(self):
        return np.isfinite(self.nn_ms)

    @property
    def n_intervals(self):
        return len(self.nn_ms)

    @property
    def n_accepted(self):
        return int(self.accepted.sum())

    @property
    def coverage(self):
        return self.n_accepted / self.n_intervals if self.n_intervals else 0.0

    @property
    def valid_s(self):
        return float(np.nansum(self.nn_ms)) / 1000.0 if self.n_intervals else 0.0

    @property
    def span_s(self):
        return float(self.beat_t[-1] - self.beat_t[0]) if len(self.beat_t) > 1 else 0.0

    @property
    def values(self):
        """Accepted intervals, ms."""
        return self.nn_ms[self.accepted]

    @property
    def times(self):
        """Time (s) of the beat that ends each accepted interval."""
        return self.beat_t[1:][self.accepted]

    def pairs(self):
        """(a, b): every accepted interval a immediately followed by an accepted b."""
        acc = self.accepted
        k = np.flatnonzero(acc[:-1] & acc[1:]) if len(acc) > 1 else np.zeros(0, dtype=int)
        return self.nn_ms[k], self.nn_ms[k + 1]

    def runs(self, min_len=1):
        """Maximal stretches of consecutive accepted intervals, each an array."""
        out, acc = [], self.accepted
        i, n = 0, len(acc)
        while i < n:
            if not acc[i]:
                i += 1; continue
            j = i
            while j < n and acc[j]:
                j += 1
            if j - i >= min_len:
                out.append(self.nn_ms[i:j])
            i = j
        return out


# ------------------------------------------------------------------ the gate
def minimum(name):
    """The minimum-window requirement of one measure, from config.json."""
    return MIN_WINDOW[name]


def gate(nn, name):
    """None when the window meets the measure's minimum duration and NN count,
    otherwise the reason it does not. Duration is the summed length of the
    ACCEPTED intervals, not the clock time of the window: a 5-minute window
    with half its beats rejected holds 2.5 minutes of data. The spectral
    measures also need a minimum coverage: missing beats raise the floor of a
    Lomb-Scargle spectrum (analysis/hrv_min_window_simulation.txt, part 2)."""
    req = MIN_WINDOW[name]
    if nn.valid_s < req["valid_s"]:
        return f"{nn.valid_s:.0f} s of valid NN intervals, needs {req['valid_s']:g} s"
    if "nn" in req and nn.n_accepted < req["nn"]:
        return f"{nn.n_accepted} accepted NN intervals, needs {req['nn']}"
    if "coverage" in req and nn.coverage < req["coverage"]:
        return f"coverage {100 * nn.coverage:.0f}%, needs {100 * req['coverage']:.0f}%"
    return None


def result(nn, name, unit, value=None, withheld=None, n_used=0, **extra):
    if value is not None and not math.isfinite(value):
        value, withheld = None, "not finite"
    return Result(name, None if value is None else float(value), unit, withheld,
                  int(n_used), nn.valid_s, nn.span_s, nn.coverage, extra)
