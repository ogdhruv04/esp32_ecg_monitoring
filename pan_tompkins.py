#!/usr/bin/env python3
"""Streaming Pan-Tompkins R-peak detector - reference implementation.

Written sample-at-a-time (not vectorised) on purpose: this is the exact
algorithm ported to BeatDetector.kt for on-device use, and a streaming
reference is the only way to be sure the port matches. Validated by
benchmark_mitdb.py --method ours before anything it produces reaches a screen.
"""
import numpy as np, math

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

class PanTompkins:
    def __init__(self, fs):
        self.fs = fs
        # Stage 1: bandpass 5-15 Hz. Narrower than the monitoring band on
        # purpose - centred on QRS energy, and it actively suppresses P and T
        # waves so they cannot be mistaken for R-peaks.
        self.hp = _rbj('hp', 5.0, 0.7071, fs)
        self.lp = _rbj('lp', 15.0, 0.7071, fs)
        self.deriv = [0.0]*5
        # History of the bandpassed signal, for locating the true R-peak. The
        # moving-window integrator peaks ~half a window (75 ms) after the QRS,
        # and wide complexes lag further still - reporting the integrator peak
        # directly put record 208's detections outside the 150 ms match window,
        # scoring them as a false positive AND a false negative simultaneously
        # (TP 2236, FP 706, FN 719 against 2955 real beats).
        self.bp_hist = [0.0] * (int(0.250*fs) + 1)
        self.bp_i = 0
        self.win = int(0.150*fs)              # ~QRS width
        self.integ = [0.0]*self.win
        self.ii = 0; self.isum = 0.0
        self.spk = self.npk = 0.0
        self.n = 0
        self.last_peak = -10**9
        self.rr = []
        self.prev = 0.0; self.rising = False
        self.pending = []          # sub-threshold candidates, for search-back
        self.peaks = []
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

    def process(self, x):
        """Feed one sample; returns index of a confirmed R-peak or None."""
        y = self.lp(self.hp(float(x)))
        self.bp_hist[self.bp_i] = abs(y)
        self.bp_i = (self.bp_i + 1) % len(self.bp_hist)
        self.deriv.pop(0); self.deriv.append(y)
        d = (2*self.deriv[4] + self.deriv[3] - self.deriv[1] - 2*self.deriv[0]) / 8.0
        sq = d*d
        self.isum += sq - self.integ[self.ii]
        self.integ[self.ii] = sq
        self.ii = (self.ii + 1) % self.win
        mwi = self.isum / self.win

        self.n += 1
        out = None

        # Track local maxima of the integrated signal.
        if mwi > self.prev:
            self.rising = True
        elif self.rising:
            self.rising = False
            out = self._candidate(self.prev, self.n - 1)
        self.prev = mwi

        if self.n < self.warmup:
            # Learning phase: seed the running estimates, emit nothing.
            self.spk = max(self.spk, mwi*0.25)
            self.npk = 0.875*self.npk + 0.125*mwi
            return None

        # Search-back. If no beat has been confirmed within 166% of the running
        # average RR, a beat was probably missed because its amplitude fell
        # under the threshold - which is what happens when QRS amplitude drifts,
        # and is the single biggest source of missed beats. Re-scan the
        # candidates we rejected using a threshold half as strict. Without this,
        # sensitivity on MIT-BIH record 228 is 52.1% (95.7% with it); overall Se
        # 94.86% -> 98.49%. See analysis/ablation_searchback_refine.txt.
        # Recover from a poisoned threshold: halve SPK once a second until
        # beats are found again. Geometric, so it recovers within a few
        # seconds from any artifact, however large.
        if (self.n - self.last_peak) > self.stall and (self.n - self.last_decay) > self.decay_every:
            self.spk = max(self.npk, self.spk * 0.5)
            self.last_decay = self.n

        if out is None and self.rr:
            avg = sum(self.rr) / len(self.rr)
            if (self.n - self.last_peak) > 1.66 * avg:
                out = self._search_back()
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
            if self.last_peak > -10**8:
                self.rr.append(idx - self.last_peak)
                if len(self.rr) > 8: self.rr.pop(0)
            r = self._refine(idx)
            self.last_peak = idx
            self.peaks.append(r)
            self.pending.clear()
            return r
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
        if self.last_peak > -10**8:
            self.rr.append(idx - self.last_peak)
            if len(self.rr) > 8: self.rr.pop(0)
        self.last_peak = idx
        self.peaks.append(self._refine(idx))
        self.pending = [(i, p) for i, p in self.pending if i > idx]
        return idx

    def _refine(self, mwi_idx):
        """Map an integrator peak back to the QRS peak in the bandpassed signal.

        Searches the last 200 ms of |bandpassed| from the current sample, so the
        returned index is n-1-best_off regardless of mwi_idx.
        """
        span = len(self.bp_hist)
        back = int(0.200 * self.fs)
        best_off, best_val = 0, -1.0
        for k in range(back):
            j = (self.bp_i - 1 - k) % span
            if self.bp_hist[j] > best_val:
                best_val, best_off = self.bp_hist[j], k
        return self.n - 1 - best_off

def detect(sig, fs):
    pt = PanTompkins(fs)
    for v in sig: pt.process(v)
    return np.array(pt.peaks, dtype=int)
