#!/usr/bin/env python3
"""Two figures the Phase-I poster quotes that no earlier analysis file printed.
Read-only on captures/; writes analysis/poster_checks.txt.

  1. Interrupt spacing in the 29 Sep link test (both boards, no electrodes):
     the gap between consecutive FIFO interrupts, measured on the ESP32's own
     micros() clock (the isr_micros column; every sample of one drain shares
     its interrupt's timestamp). The MAX30003 asks for service every 4 samples,
     so the nominal gap is 4/256 s = 15,625 us.

  2. Where the finger-vs-chest numbers of the simultaneous recording (dual03)
     come from, with the shipped detector and its timing point (tp3), on the
     phone's causal filter, as evaluate_tp3.py own: the Bland-Altman intervals
     (consecutive matched beats, left out when any of their four beats is
     flagged at either site) and each site's NN coverage, split by why an
     interval was not used.

    ./poster_checks.py
"""
import os, subprocess, sys
import numpy as np

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO); os.chdir(REPO)
import pan_tompkins as PT
from algorithms import frontend

FS = 256.0
LINK = "captures/20260929_152557_linktest_noelectrodes_{}.csv"
DUAL = "captures/20260929_163314_dual03_both3wire_c3chest_wroomfinger_{}.csv"   # ring = chest, ref = finger
OUT = "analysis/poster_checks.txt"
lines = []
say = lines.append


def read(path):
    return np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8", invalid_raise=False)


def greedy(ref_t, test_t, tol):
    """evaluate_tp3.greedy: one-to-one matching within tol, in test order."""
    used = np.zeros(len(ref_t), bool); pairs = []
    for j, t in enumerate(test_t):
        i = np.searchsorted(ref_t, t)
        best, bd = -1, tol + 1
        for k in (i - 1, i, i + 1):
            if 0 <= k < len(ref_t) and not used[k] and abs(ref_t[k] - t) < bd:
                best, bd = k, abs(ref_t[k] - t)
        if best >= 0 and bd <= tol:
            used[best] = True; pairs.append((best, j))
    return pairs


def load_dual(path):
    """evaluate_tp3.own_dual's loader: skip 10 s, keep the longest unbroken run."""
    raw = read(path)
    idx = raw["index"].astype(np.int64); val = raw["value"].astype(float); host = raw["host_time"].astype(float)
    s = int(10.0 * FS); idx, val, host = idx[s:], val[s:], host[s:]
    br = np.flatnonzero(np.diff(idx) != 1) + 1
    keep = max(np.split(np.arange(len(idx)), br), key=len)
    return val[keep], float(host[keep][0])


commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(["git", "status", "--porcelain", "--", "pan_tompkins.py", "tp2_config.json", "algorithms"],
                       capture_output=True, text=True).stdout.strip()
say(f"# ./poster_checks.py   commit {commit}{' + uncommitted changes' if dirty else ''}; detector {PT.TIMING_POINT}")
say("# Figures quoted on the Phase-I poster that no earlier analysis file printed. Read-only on captures/.")
say("")

# ---------------------------------------------------------------- 1. interrupt spacing
say("=== 1. Interrupt spacing, link test 29 Sep (no electrodes), on the ESP32 micros() clock ===")
say("nominal 4 samples / 256 SPS = 15625 us. One gap = time between two consecutive FIFO interrupts.")
for board in ("ring", "ref"):
    r = read(LINK.format(board))
    us = r["isr_micros"].astype(np.int64)
    drains = us[np.r_[True, np.diff(us) != 0]]
    g = np.diff(drains); g = g[(g > 0) & (g < 1_000_000)]
    p1, p99 = np.percentile(g, [1, 99])
    say(f"{board:4}: {len(g)} gaps; median {np.median(g):.0f} us; 1st-99th percentile {p1:.0f}-{p99:.0f} us; "
        f"min {g.min()} max {g.max()} us; within +-2 us of 15625: {100*np.mean(np.abs(g-15625) <= 2):.1f}%")
say("The gap is timed by the ESP32's clock and the interrupt's latency, so this shows regular service, not the")
say("MAX30003's sample rate: microsecond resolution cannot see ppm-level oscillator differences.")
say("")

# ---------------------------------------------------------------- 2. dual03 interval counts
say("=== 2. Simultaneous finger and chest recording (dual03), causal filter, shipped detector (tp3) ===")
(cx, ch0), (fx, fh0) = load_dual(DUAL.format("ring")), load_dual(DUAL.format("ref"))
site = {}
for name, x, h0 in (("chest", cx, ch0), ("finger", fx, fh0)):
    y = frontend.filter_ecg(x, FS, 50.0, causal=True, harmonic=True)
    pt = PT.PanTompkins(FS)
    for v in y:
        pt.process(v)
    site[name] = dict(h0=h0, beats=pt.beats)
tc = site["chest"]["h0"] + np.array([b["bp"] for b in site["chest"]["beats"]], float) / FS
tf = site["finger"]["h0"] + np.array([b["bp"] for b in site["finger"]["beats"]], float) / FS
off = 0.0
for _ in range(4):
    j = np.clip(np.searchsorted(tc, tf - off), 1, len(tc) - 1)
    near = np.where(np.abs(tc[j] - (tf - off)) < np.abs(tc[j - 1] - (tf - off)), j, j - 1)
    dd = (tf - off) - tc[near]; off += float(np.median(dd[np.abs(dd) < 0.15]))
pairs = greedy(tc, tf - off, 0.15)
ic = np.array([p[0] for p in pairs]); jf = np.array([p[1] for p in pairs])
cons = np.flatnonzero((np.diff(ic) == 1) & (np.diff(jf) == 1))
pc = np.array([b["pos"] for b in site["chest"]["beats"]]) / FS * 1000; fc = np.array([b["flagged"] for b in site["chest"]["beats"]])
pf = np.array([b["pos"] for b in site["finger"]["beats"]]) / FS * 1000; ff = np.array([b["flagged"] for b in site["finger"]["beats"]])
bad = fc[ic[cons]] | fc[ic[cons + 1]] | ff[jf[cons]] | ff[jf[cons + 1]]
drr = ((pf[jf[cons + 1]] - pf[jf[cons]]) - (pc[ic[cons + 1]] - pc[ic[cons]]))[~bad]
mu, sd = float(drr.mean()), float(drr.std(ddof=1))
say(f"beats: chest {len(tc)}, finger {len(tf)}; matched {len(pairs)} (150 ms, offset {1000*off:+.0f} ms)")
say(f"flagged by the timing step (tp3): chest {int(fc.sum())}, finger {int(ff.sum())}")
say(f"Bland-Altman intervals: {len(cons)} consecutive matched intervals; {int(bad.sum())} left out because one of their "
    f"four beats is flagged at either site; {int((~bad).sum())} used")
say(f"  finger - chest RR: bias {mu:+.2f} ms, limits {mu-1.96*sd:+.1f} .. {mu+1.96*sd:+.1f} ms (n {len(drr)}; "
    f"analysis/tp3_own_recordings.txt prints -1.8..+1.8, n 166)")
say("  The 20% NN rule is NOT applied to these intervals; it belongs to the RMSSD below.")
say("NN series per site (pan_tompkins.rr_history + clean_nn, as the RMSSD in tp3_own_recordings.txt):")
for name in ("chest", "finger"):
    rr = PT.rr_history(site[name]["beats"], FS, depth=10**9)
    acc, dropped = PT.clean_nn(rr)
    v, nacc, _, cov = PT.rmssd_nn(rr)
    nan = sum(1 for m in rr if m != m)
    out = sum(1 for m in rr if m == m and not (300.0 <= m <= 2000.0))
    say(f"  {name:6}: {len(rr)} inter-beat intervals; {nacc} accepted ({100*cov:.1f}%); not used: {nan} next to a flagged "
        f"or searched-back beat, {out} outside 300-2000 ms, {dropped} by the 20% rule; RMSSD {v:.1f} ms")

with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines)); print(f"\nwrote {OUT}")
