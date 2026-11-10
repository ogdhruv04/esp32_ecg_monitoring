#!/usr/bin/env python3
"""Streaming Pan-Tompkins R-peak detector - reference implementation.

Written sample-at-a-time (not vectorised) on purpose: this is the exact
algorithm ported to BeatDetector.kt for on-device use, and a streaming
reference is the only way to be sure the port matches. Validated by
benchmark_mitdb.py --method ours before anything it produces reaches a screen.

Beat positions are timing point 2 (tp2, from 23 Oct 2026): the peak of the
dominant QRS deflection in the input, with parabolic sub-sample interpolation
and an artifact guard, validated in fiducial.py v2. Results produced before
that used tp1 (the sample of max |5-15 Hz bandpassed|); those files are kept
and carry no tp label.
"""
import json, math, os
import numpy as np

# Every tp2 and HRV parameter is frozen in tp2_config.json (BeatDetector.kt
# hard-codes the same values; BeatDetectorConfigTest checks they match).
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tp2_config.json")) as _f:
    CONFIG = json.load(_f)
TIMING_POINT = CONFIG["version"]   # written into result files; see the module docstring

class Biquad:
    def __init__(s, b0, b1, b2, a1, a2):
        s.b = (b0, b1, b2); s.a = (a1, a2); s.z1 = s.z2 = 0.0
    def __call__(s, x):
        y = s.b[0]*x + s.z1
        s.z1 = s.b[1]*x - s.a[0]*y + s.z2
        s.z2 = s.b[2]*x - s.a[1]*y
        return y

def _rbj(kind, f0, q, fs):
    w0 = 2*math.pi*f0/fs; c = math.cos(w0); al = math.sin(w0)/(2*q); a0 = 1+al
    if kind == 'lp': b = [(1-c)/2, 1-c, (1-c)/2]
    else:            b = [(1+c)/2, -(1+c), (1+c)/2]
    return Biquad(b[0]/a0, b[1]/a0, b[2]/a0, (-2*c)/a0, (1-al)/a0)

def _parabolic(a, b, c):
    """Vertex offset (samples, |d| <= 0.5) of the parabola through three
    neighbouring samples with b in the middle; 0 unless b is a local maximum."""
    den = a - 2.0*b + c
    if not (den < 0.0 and b >= a and b >= c):
        return 0.0
    return min(0.5, max(-0.5, 0.5*(a - c)/den))

def _detrend(w):
    """Subtract the straight line through the means of the first and last 3 samples."""
    n = len(w)
    a = (w[0] + w[1] + w[2]) / 3.0
    b = (w[n-3] + w[n-2] + w[n-1]) / 3.0
    return [w[i] - (a + (b - a) * i / (n - 1)) for i in range(n)]

def _median(v):
    s = sorted(v); m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m-1] + s[m]) / 2.0

class PanTompkins:
    # tp2 parameters, from tp2_config.json:
    #   R_BEFORE_S, R_AFTER_S  R search window around the 5-15 Hz peak
    #   POL_KEEP, POL_MIN, POL_RATIO  rolling median beat for polarity
    #   EDGE      a maximum this close to the window edge is no peak
    #   HIST_S    history kept for refining (covers search-back)
    #   CORR_MIN  per-beat check: flag a beat whose best-aligned correlation with
    #             the median beat is below this (set None on an instance for "off")
    #   CORR_LAG  +-samples searched for that best alignment
    _c = CONFIG["detector"]
    R_BEFORE_S, R_AFTER_S = _c["R_BEFORE_S"], _c["R_AFTER_S"]
    POL_KEEP, POL_MIN, POL_RATIO = _c["POL_KEEP"], _c["POL_MIN"], _c["POL_RATIO"]
    EDGE, HIST_S = _c["EDGE"], _c["HIST_S"]
    CORR_MIN, CORR_LAG = _c["CORR_MIN"], _c["CORR_LAG"]

    def __init__(self, fs):
        self.fs = fs
        # Stage 1: bandpass 5-15 Hz. Narrower than the monitoring band on
        # purpose - centred on QRS energy, and it actively suppresses P and T
        # waves so they cannot be mistaken for R-peaks.
        self.hp = _rbj('hp', 5.0, 0.7071, fs)
        self.lp = _rbj('lp', 15.0, 0.7071, fs)
        self.deriv = [0.0]*5
        # History of the input and of |bandpassed|, indexed by absolute sample
        # number (slot i % H). The integrator peaks ~half a window (75 ms) after
        # the QRS, so the beat is located back in these. Search-back can refine a
        # beat up to ~3.5 s old, hence 4 s. Slots skipped by skip() hold NaN, so
        # no window can silently read stale data.
        self.H = int(self.HIST_S*fs)
        self.xh = [math.nan]*self.H
        self.bph = [math.nan]*self.H
        self.win = int(0.150*fs)              # ~QRS width
        self.integ = [0.0]*self.win
        self.ii = 0; self.isum = 0.0
        self.spk = self.npk = 0.0
        self.n = 0
        self.last_peak = -10**9
        self.rr = []
        self.prev = 0.0; self.rising = False
        self.pending = []          # sub-threshold candidates, for search-back
        self.refractory = int(0.200*fs)       # absolute cardiac refractory
        self.warmup = int(2.0*fs)
        # Threshold decay. A transient far larger than any R-peak - electrodes
        # settling, a knock on the lead - drives SPK so high that nothing
        # reaches the threshold again. Search-back cannot rescue it, because
        # search-back needs an RR history and none is ever built. The detector
        # then produces NOTHING for the rest of the recording, silently: on a
        # real chest capture it found 10 beats in 4.5 minutes. MIT-BIH never
        # exposed this because those records start already settled.
        self.stall = int(3.0*fs)              # 3 s without a beat = under 20 bpm
        self.decay_every = int(1.0*fs)
        self.last_decay = 0
        # Set by skip(): samples were lost since the last beat, so the next RR
        # interval spans a hole and may hide a beat. It is not recorded.
        self.gap_pending = False
        # tp2 state
        self.lo = int(self.R_BEFORE_S*fs); self.hi = int(self.R_AFTER_S*fs)
        self.segs = []             # previous beats' input windows, for polarity
        # Outputs. Every accepted beat, warm-up included (process() returns
        # only those after the warm-up, as the phone shows).
        self.peaks = []            # tp2 positions, fractional sample index
        self.bp_peaks = []         # 5-15 Hz peak index (tp1), for fiducial.py
        self.beats = []            # dicts: pos, bp, kind, flagged, gap - for HRV
        self.clamped = 0           # beats located before their R window had arrived (should stay 0)
        self.corr_flagged = 0      # beats flagged by the per-beat correlation check
        # A beat is located only once its whole R window has arrived: the
        # integrator often fires less than 60 ms after the 5-15 Hz peak (on
        # 30-70% of beats), and a truncated window shifts the detrend and
        # starves the polarity template. Beats are >= 200 ms apart, so at most
        # one waits, for at most R_AFTER_S.
        self.unfinished = None

    # ------------------------------------------------------------- history
    def _x(self, i):
        return self.xh[i % self.H] if self.n - self.H <= i <= self.n - 1 and i >= 0 else math.nan

    def _bp(self, i):
        return self.bph[i % self.H] if self.n - self.H <= i <= self.n - 1 and i >= 0 else math.nan

    def skip(self, samples):
        """Tell the detector that `samples` samples were lost in transit.

        The clock moves on by the lost count, so later beat indices and RR
        intervals stay on the true timeline. Feeding nothing would compress time:
        on the phone, one lost BLE packet would shorten an RR interval by 23 ms.
        The interval spanning the gap is dropped, not recorded, because a beat
        may have fallen inside the hole. The filters are not reset; the splice
        is a small step they absorb.
        """
        if samples <= 0:
            return
        for i in range(self.n, self.n + min(samples, self.H)):
            self.xh[i % self.H] = math.nan; self.bph[i % self.H] = math.nan
        self.n += samples
        self.gap_pending = True

    def process(self, x):
        """Feed one sample. Returns the tp2 position (fractional sample index)
        of a confirmed beat, or None."""
        x = float(x)
        y = self.lp(self.hp(x))
        slot = self.n % self.H
        self.xh[slot] = x; self.bph[slot] = abs(y)
        self.deriv.pop(0); self.deriv.append(y)
        d = (2*self.deriv[4] + self.deriv[3] - self.deriv[1] - 2*self.deriv[0]) / 8.0
        sq = d*d
        self.isum += sq - self.integ[self.ii]
        self.integ[self.ii] = sq
        self.ii = (self.ii + 1) % self.win
        mwi = self.isum / self.win

        self.n += 1
        out = None
        if self.unfinished is not None and self.unfinished["d"] + self.hi <= self.n - 1:
            out = self._finish()

        # Track local maxima of the integrated signal.
        if mwi > self.prev:
            self.rising = True
        elif self.rising:
            self.rising = False
            r = self._candidate(self.prev, self.n - 1)
            if r is not None: out = r
        self.prev = mwi

        if self.n < self.warmup:
            # Learning phase: seed the running estimates, and return nothing.
            # Candidates are still judged, so `peaks` - the offline output that
            # benchmark_mitdb.py and agreement.py read - does include beats from
            # these first 2 s. The phone shows only what process() returns, so
            # BeatDetector.kt emits nothing here; the internal state is the same.
            self.spk = max(self.spk, mwi*0.25)
            self.npk = 0.875*self.npk + 0.125*mwi
            return None

        # Recover from a poisoned threshold: halve SPK once a second until
        # beats are found again. Geometric, so it recovers within a few
        # seconds from any artifact, however large.
        if (self.n - self.last_peak) > self.stall and (self.n - self.last_decay) > self.decay_every:
            self.spk = max(self.npk, self.spk * 0.5)
            self.last_decay = self.n

        # Search-back. If no beat has been confirmed within 166% of the running
        # average RR, a beat was probably missed because its amplitude fell
        # under the threshold - which is what happens when QRS amplitude drifts,
        # and is the single biggest source of missed beats. Re-scan the
        # candidates we rejected using a threshold half as strict. Without this,
        # sensitivity on MIT-BIH record 228 is 52.1% (95.7% with it); overall Se
        # 94.86% -> 98.49%. See analysis/ablation_searchback_refine.txt (tp1).
        if self.rr and self.unfinished is None:
            avg = sum(self.rr) / len(self.rr)
            if (self.n - self.last_peak) > 1.66 * avg:
                r = self._search_back()
                if r is not None: out = r
        return out

    def _candidate(self, peak, idx):
        thr1 = self.npk + 0.25*(self.spk - self.npk)
        if peak > thr1 and (idx - self.last_peak) > self.refractory:
            # T-wave discrimination: a candidate arriving 200-360 ms after a
            # confirmed beat with less than half the amplitude is a T wave.
            if self.rr and (idx - self.last_peak) < 0.36*self.fs and peak < 0.5*self.spk:
                self.npk = 0.875*self.npk + 0.125*peak
                return None
            self.spk = 0.875*self.spk + 0.125*peak
            if self.last_peak > -10**8 and not self.gap_pending:
                self.rr.append(idx - self.last_peak)
                if len(self.rr) > 8: self.rr.pop(0)
            gap = self.gap_pending
            self.gap_pending = False
            self.last_peak = idx
            self.pending.clear()
            return self._accept(idx, "primary", gap)
        self.npk = 0.875*self.npk + 0.125*peak
        # Remember it in case search-back needs to reconsider it later.
        if idx - self.last_peak > self.refractory:
            self.pending.append((idx, peak))
            if len(self.pending) > 64: self.pending.pop(0)
        return None

    def _search_back(self):
        thr1 = self.npk + 0.25*(self.spk - self.npk)
        thr2 = 0.5 * thr1
        best = None
        for idx, peak in self.pending:
            if idx - self.last_peak <= self.refractory:
                continue
            if peak > thr2 and (best is None or peak > best[1]):
                best = (idx, peak)
        if best is None:
            return None
        idx, peak = best
        # A searched-back beat updates SPK with a smaller step (0.25 rather than
        # 0.125 weighting on the running value) per the original paper - it is a
        # lower-confidence detection and should not yank the threshold around.
        self.spk = 0.75*self.spk + 0.25*peak
        if self.last_peak > -10**8 and not self.gap_pending:
            self.rr.append(idx - self.last_peak)
            if len(self.rr) > 8: self.rr.pop(0)
        gap = self.gap_pending
        self.gap_pending = False
        self.last_peak = idx
        self.pending = [(i, p) for i, p in self.pending if i > idx]
        return self._accept(idx, "searchback", gap)

    # ----------------------------------------------------------- locating
    def _bp_refine(self, mwi_idx):
        """The 5-15 Hz peak (tp1): max |bandpassed| over the 200 ms ending at the
        beat's own integrator index. Up to 23 Oct 2026 this searched back from
        the CURRENT sample instead, which for search-back - firing up to 1.66 RR
        later - could land on a different beat. Returns (index, ok)."""
        back = int(0.200 * self.fs)
        best_i, best_v = mwi_idx, -1.0
        for k in range(back):
            v = self._bp(mwi_idx - k)
            if v == v and v > best_v:          # v == v: not NaN
                best_v, best_i = v, mwi_idx - k
        return best_i, best_v >= 0.0

    def _polarity(self):
        """(sign, median beat). Sign of the median of the previous beats'
        windows: +1/-1 when one lobe is at least POL_RATIO x the other, 0
        (undecided) otherwise or with fewer than POL_MIN beats. Never decided
        from the current beat alone. The median beat is detrended, None when
        there are too few beats."""
        if len(self.segs) < self.POL_MIN:
            return 0, None
        L = len(self.segs[0])
        t = _detrend([_median([s[i] for s in self.segs]) for i in range(L)])
        pos = max(t); neg = -min(t)
        if pos >= self.POL_RATIO * neg:
            return 1, t
        if neg >= self.POL_RATIO * pos:
            return -1, t
        return 0, t

    def _corr_with(self, t, d):
        """Correlation of this beat's window with the median beat t at the lag
        (within +-CORR_LAG samples) where |r| is largest, both detrended and
        mean-removed over their overlap. Taking the best alignment matters: the
        window is anchored on the 5-15 Hz peak, which can sit +-39 ms off the R
        peak, and an unaligned normal beat can correlate negatively with its own
        median beat. An inverted beat still gives r near -1 at its best lag.
        NaN when it cannot be computed."""
        w = [self._x(i) for i in range(d - self.lo, d + self.hi + 1)]
        if len(w) != len(t) or any(v != v for v in w):
            return math.nan
        w = _detrend(w)
        best = math.nan
        L = len(w)
        for lag in range(-self.CORR_LAG, self.CORR_LAG + 1):
            i0 = max(0, -lag); i1 = min(L, L - lag)     # t[i] against w[i + lag]
            m = i1 - i0
            if m < L // 2:
                continue
            mw = sum(w[i + lag] for i in range(i0, i1)) / m
            mt = sum(t[i] for i in range(i0, i1)) / m
            sab = saa = sbb = 0.0
            for i in range(i0, i1):
                a = w[i + lag] - mw; b = t[i] - mt
                sab += a * b; saa += a * a; sbb += b * b
            if saa <= 0.0 or sbb <= 0.0:
                continue
            r = sab / math.sqrt(saa * sbb)
            if best != best or abs(r) > abs(best):
                best = r
        return best

    def _tp2(self, d, sign):
        """R peak + parabolic + guard around the 5-15 Hz peak d.
        Returns (position, flagged)."""
        a, b, c = self._bp(d - 1), self._bp(d), self._bp(d + 1)
        fallback = d + (_parabolic(a, b, c) if a == a and b == b and c == c else 0.0)
        if sign == 0:
            return fallback, True, fallback
        start = d - self.lo
        end = d + self.hi
        if end > self.n - 1:
            end = self.n - 1; self.clamped += 1
        w = [sign * self._x(i) for i in range(start, end + 1)]
        if len(w) < 2*self.EDGE + 3 or any(v != v for v in w):
            return fallback, True, fallback
        wd = _detrend(w)
        k = 0
        for i in range(1, len(wd)):
            if wd[i] > wd[k]:
                k = i
        if k < self.EDGE or k > len(wd) - 1 - self.EDGE:
            return fallback, True, fallback
        return start + k + _parabolic(wd[k-1], wd[k], wd[k+1]), False, fallback

    def _accept(self, mwi_idx, kind, gap):
        """A beat was detected. Locate it now if its R window has arrived (always
        so for search-back), otherwise when it has. Returns the position if it
        was located now and the warm-up is over, else None."""
        if self.unfinished is not None:        # cannot happen at >= 200 ms spacing
            self._finish()
        d, ok = self._bp_refine(mwi_idx)
        self.unfinished = dict(mwi=mwi_idx, d=d, ok=ok, kind=kind, gap=gap,
                               warm=self.n < self.warmup)
        if not ok or d + self.hi <= self.n - 1:
            return self._finish()
        return None

    def _finish(self):
        u = self.unfinished; self.unfinished = None
        d, ok, mwi_idx, kind, gap = u["d"], u["ok"], u["mwi"], u["kind"], u["gap"]
        sign, tmpl = self._polarity()
        pos, flagged, fallback = self._tp2(d, sign) if ok else (float(mwi_idx), True, float(mwi_idx))
        # Per-beat CHECK against the median beat (not a per-beat decision): a beat
        # whose window anti-correlates with it is inverted relative to the
        # template - after a real polarity change, the template keeps the old
        # sign for several beats and would time them on the wrong lobe.
        if not flagged and self.CORR_MIN is not None:
            r = self._corr_with(tmpl, d)
            if not (r >= self.CORR_MIN):          # NaN fails too
                pos, flagged = fallback, True
                self.corr_flagged += 1
        # This beat's window joins the polarity template AFTER its own sign
        # was set, and only when the whole window has arrived.
        if ok and d + self.hi <= self.n - 1:
            seg = [self._x(i) for i in range(d - self.lo, d + self.hi + 1)]
            if all(v == v for v in seg):
                self.segs.append(seg)
                if len(self.segs) > self.POL_KEEP: self.segs.pop(0)
        self.peaks.append(pos); self.bp_peaks.append(d)
        self.beats.append(dict(pos=pos, bp=d, kind=kind, flagged=flagged, gap=gap))
        # Same rule as before deferral: beats DETECTED in the warm-up are kept
        # in `peaks` and the HRV history but never returned.
        return None if u["warm"] else pos

# ------------------------------------------------------------------ HRV reference
_h = CONFIG["hrv"]
NN_STEP, NN_SEED = _h["NN_STEP"], _h["NN_SEED"]
HRV_DEPTH, MIN_BEATS_FOR_HRV = _h["HRV_DEPTH"], _h["MIN_BEATS_FOR_HRV"]

def rr_history(beats, fs, depth=HRV_DEPTH):
    """The phone's rrHist (BeatDetector.kt), in ms: ONE entry per inter-beat
    interval, so coverage (accepted / entries) means "share of beats whose
    interval is used". An interval is NaN unless both its beats are primary
    and unflagged and no samples were lost between them. The newest `depth`
    entries are kept."""
    hist, last, seen = [], None, False
    for b in beats:
        usable = b["kind"] == "primary" and not b["flagged"]
        if seen:
            hist.append(1000.0 * (b["pos"] - last) / fs
                        if usable and last is not None and not b["gap"] else math.nan)
        seen = True
        last = b["pos"] if usable else None
    return hist[-depth:]

def clean_nn(rr_ms):
    """NN cleaning. Valid = 300-2000 ms (NaN is never valid). A valid interval
    more than NN_STEP (20%) from the previous ACCEPTED interval is dropped. The
    reference is seeded from the median of the first NN_SEED valid intervals -
    one spurious first interval otherwise rejects everything after it - and
    re-seeded from the median of NN_SEED consecutive drops, so a real step
    change in rate cannot lock it out. Returns (accepted mask, n_dropped)."""
    acc = [False]*len(rr_ms)
    valid = [i for i, m in enumerate(rr_ms) if m == m and 300.0 <= m <= 2000.0]
    if not valid:
        return acc, 0
    ref = _median([rr_ms[i] for i in valid[:NN_SEED]])
    run, dropped = [], 0
    for i in valid:
        m = rr_ms[i]
        if abs(m - ref) > NN_STEP * ref:
            dropped += 1; run.append(m)
            if len(run) >= NN_SEED:
                ref = _median(run); run = []
            continue
        acc[i] = True; ref = m; run = []
    return acc, dropped

def rmssd_nn(rr_ms):
    """RMSSD (ms) on the cleaned NN series, differences only between two accepted
    intervals that are adjacent. Returns (rmssd or None, n_accepted, n_dropped,
    coverage), coverage = accepted / all entries of rr_ms; rmssd is None with
    fewer than MIN_BEATS_FOR_HRV accepted intervals or 5 differences."""
    acc, dropped = clean_nn(rr_ms)
    s, k = 0.0, 0
    for i in range(1, len(rr_ms)):
        if acc[i] and acc[i-1]:
            dd = rr_ms[i] - rr_ms[i-1]; s += dd*dd; k += 1
    n_acc = sum(acc)
    cov = n_acc / len(rr_ms) if rr_ms else 0.0
    if n_acc < MIN_BEATS_FOR_HRV or k < 5:
        return None, n_acc, dropped, cov
    return math.sqrt(s / k), n_acc, dropped, cov

def detect(sig, fs, with_flags=False):
    """tp2 positions (fractional sample index) of every accepted beat, warm-up
    included; with_flags=True also returns the per-beat flagged mask. A beat
    still waiting for its R window when the signal ends is dropped."""
    pt = PanTompkins(fs)
    for v in sig: pt.process(v)
    pos = np.array(pt.peaks, dtype=float)
    if with_flags:
        return pos, np.array([b["flagged"] for b in pt.beats], dtype=bool)
    return pos
