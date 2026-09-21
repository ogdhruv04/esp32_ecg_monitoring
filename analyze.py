#!/usr/bin/env python3
"""Analyse a capture from capture.py: integrity, filtering, beats, HRV, SQI.

    ./analyze.py captures/20260819_153444_sweepfix.csv

Deliberately reports data integrity *before* anything derived from it. A filter
cannot tell you whether its own output is real: bandpass pure noise and you get
a plausible squiggle, and a peak detector will happily report 72 bpm from it.
So the integrity block is the part that decides whether the rest means anything.
"""
import argparse, pathlib, sys
import numpy as np
from scipy import signal as sps
from scipy.stats import kurtosis

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("--fs", type=float, default=256.0)
ap.add_argument("--mains", type=float, default=50.0, help="powerline freq (India = 50)")
ap.add_argument("--plot", action="store_true")
args = ap.parse_args()

path = pathlib.Path(args.csv)
raw = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding=None)
idx     = raw["index"].astype(np.int64)
micros  = raw["isr_micros"].astype(np.int64)
value   = raw["value"].astype(np.float64)
etag    = raw["etag"].astype(np.int64)
leadoff = raw["leadoff"].astype(np.int64) if "leadoff" in raw.dtype.names else np.zeros_like(etag)

# A device reset mid-capture restarts the sample index at 1, so the file holds
# two sessions end to end. Concatenating them injects a huge artificial jump:
# it showed up as "-7635 missing samples (-105%)", kurtosis of 159, and an RMSSD
# of 602 ms. Split on any backwards step in the index and keep the longest run.
resets = np.where(np.diff(idx) < 0)[0]
if len(resets):
    bounds = [0, *(resets + 1), len(idx)]
    segs = [(bounds[i], bounds[i+1]) for i in range(len(bounds)-1)]
    a, b = max(segs, key=lambda t: t[1]-t[0])
    print(f"\n!! {len(resets)} device reset(s) mid-capture - file holds "
          f"{len(segs)} sessions of length {[e-s for s, e in segs]}")
    print(f"   analysing the longest run only (samples {a}..{b})")
    idx, micros, value, etag, leadoff = (v[a:b] for v in (idx, micros, value, etag, leadoff))

n = len(idx)
print(f"\n=== {path.name} ===")
print(f"samples: {n}   duration: {n/args.fs:.1f} s @ {args.fs:g} SPS assumed\n")

# --- 1. Integrity ----------------------------------------------------------
print("--- integrity ---")
span    = idx[-1] - idx[0] + 1
missing = span - n
print(f"  index span        : {idx[0]}..{idx[-1]}  ({span})")
print(f"  missing samples   : {missing}  ({100*missing/span:.4f}%)")

# ETAG 0/1 = valid, 2/3 = valid + end-of-FIFO. 7 = overflow, and an overflowed
# FIFO returns stale data that looks entirely plausible on a plot.
bad = int(np.sum(~np.isin(etag, [0, 1, 2, 3])))
print(f"  non-valid ETAG    : {bad}")

# The 6 LSBs of the FIFO word are ETAG/PTAG, not signal. If the shift is ever
# dropped again this catches it instantly: every value would be congruent mod 64.
if n > 64 and len(np.unique(value.astype(np.int64) % 64)) == 1:
    print("  !! all values share one residue mod 64 - the 6-bit shift is missing")

off_frac = float(np.mean(leadoff != 0))
print(f"  lead-off flagged  : {100*off_frac:.1f}% of samples  (hardware DC lead-off)")
if off_frac > 0.5:
    print("     -> NOT a reliable contact signal on this build; see caveat below.")

# Device clock: micros() is captured in the ISR, so it timestamps the FIFO
# threshold event. Used to verify the rate, not as the time base.
if micros[-1] > micros[0]:
    dev_fs = (span - 1) / ((micros[-1] - micros[0]) / 1e6)
    print(f"  measured rate     : {dev_fs:.3f} SPS")

# NOTE: lead-off is reported but deliberately NOT used as a gate.
#
# Captures before 2026-08-20 have a MISLABELLED leadoff column: the firmware
# extracted STATUS bits [11:8] (PLLINT/SAMP/RRINT/LONINT) instead of the real
# lead-off bits [3:0]. The "~100% lead-off" seen on clean recordings was the
# SAMP flag, which is supposed to be set. Those columns mean nothing; the ECG
# samples in the same files are unaffected.
#
# Even with the right bits, treat this as unconfigured: begin() leaves CNFG_GEN
# IMAG (lead-off current, bits [10:8]) at 000, so how much current the
# comparators actually get still needs verifying against known-off electrodes.
print()

# --- 2. Filter chain -------------------------------------------------------
# The MAX30003 already applies a 0.5 Hz digital HPF and a 40 Hz LPF in hardware
# (CNFG_ECG DHPF/DLPF). These stages are deliberately re-applied in software
# anyway: the hardware corners are fixed, and we need an explicit, documented
# chain we control for the validation report.
x = value - np.mean(value)
sos_hp = sps.butter(2, 0.5, "highpass", fs=args.fs, output="sos")
x = sps.sosfiltfilt(sos_hp, x)                      # zero-phase: no time shift

b_n, a_n = sps.iirnotch(args.mains, 30.0, fs=args.fs)
x = sps.filtfilt(b_n, a_n, x)
if args.fs > 2 * 2 * args.mains:                    # 2nd harmonic in band?
    b2, a2 = sps.iirnotch(2 * args.mains, 30.0, fs=args.fs)
    x = sps.filtfilt(b2, a2, x)

sos_lp = sps.butter(4, 40.0, "lowpass", fs=args.fs, output="sos")
ecg = sps.sosfiltfilt(sos_lp, x)

print("--- filtering ---")
print(f"  0.5 Hz HP (zero-phase) -> {args.mains:g} Hz notch -> 40 Hz LP")

def bands(sig):
    f, pxx = sps.welch(sig - np.mean(sig), fs=args.fs, nperseg=min(1024, n))
    def b(lo, hi):
        m = (f >= lo) & (f < hi)
        return float(np.trapezoid(pxx[m], f[m]))
    return b, (b(0, args.fs / 2) or 1.0)

# Raw spectrum characterises the front end (how much mains we are fighting).
rb, rtot = bands(value)
mains_frac = rb(args.mains - 2, args.mains + 2) / rtot
print(f"  raw  <0.5Hz drift        : {100*rb(0,0.5)/rtot:5.1f}%")
print(f"  raw  5-15Hz (QRS band)   : {100*rb(5,15)/rtot:5.1f}%")
print(f"  raw  {args.mains:g}Hz +/-2Hz mains    : {100*mains_frac:5.1f}%")
if mains_frac > 0.5:
    print("     -> mains dominates the RAW signal. The notch removes it, but this")
    print("        is real front-end noise: check RBIAS / grounding / cable routing.")

# SQI must be computed AFTER filtering. On the raw spectrum a 50 Hz-dominated
# recording scores pSQI ~0.01 even when the underlying QRS is textbook-clean,
# which would reject good data for a reason the filter chain already handles.
band, tot = bands(ecg)

# --- 3. Beats --------------------------------------------------------------
print("\n--- beats ---")
try:
    import neurokit2 as nk
    _, info = nk.ecg_peaks(ecg, sampling_rate=args.fs, method="neurokit")
    rp_a = np.asarray(info["ECG_R_Peaks"], dtype=int)
    _, info2 = nk.ecg_peaks(ecg, sampling_rate=args.fs, method="pantompkins1985")
    rp_b = np.asarray(info2["ECG_R_Peaks"], dtype=int)
except Exception as e:
    print(f"  neurokit2 unavailable ({e}); skipping")
    rp_a = rp_b = np.array([], dtype=int)

if len(rp_a) > 2:
    rr = np.diff(rp_a) / args.fs * 1000.0          # ms
    # Physiologically implausible RR intervals are almost always detector errors
    # rather than arrhythmia, and they wreck RMSSD if left in.
    ok = (rr > 300) & (rr < 2000)
    rr_ok = rr[ok]
    print(f"  R-peaks (neurokit)   : {len(rp_a)}")
    print(f"  R-peaks (pan-tompkins): {len(rp_b)}")
    if len(rr_ok) > 2:
        hr = 60000.0 / rr_ok
        print(f"  mean HR              : {hr.mean():.1f} bpm  (sd {hr.std():.1f})")
        print(f"  mean RR              : {rr_ok.mean():.1f} ms")
        print(f"  RMSSD                : {np.sqrt(np.mean(np.diff(rr_ok)**2)):.1f} ms")
        print(f"  SDNN                 : {rr_ok.std(ddof=1):.1f} ms")
        print(f"  implausible RR       : {int((~ok).sum())} of {len(rr)}")

    # --- 4. SQI ---
    # bSQI: two independent detectors agree on real beats and diverge on noise.
    # It needs no reference recording, which makes it the one quality number we
    # can compute honestly today.
    print("\n--- signal quality ---")
    tol = int(0.15 * args.fs)
    if len(rp_b):
        matched = sum(1 for p in rp_a if np.min(np.abs(rp_b - p)) <= tol)
        union = len(rp_a) + len(rp_b) - matched
        print(f"  bSQI (detector agreement): {matched/union:.3f}" if union else "  bSQI: n/a")
    print(f"  kSQI (kurtosis)          : {kurtosis(ecg, fisher=False):.2f}   (clean ECG >5, gaussian noise ~3)")
    print(f"  pSQI (5-15Hz / total)    : {band(5,15)/tot:.3f}")
    print(f"  lead-off clean fraction  : {1-off_frac:.3f}  (see caveat above)")

    print("\n--- verdict ---")
    reasons = []
    if missing: reasons.append(f"{missing} missing samples")
    if bad:     reasons.append(f"{bad} non-valid ETAG")
    ks = kurtosis(ecg, fisher=False)
    ps = band(5, 15) / tot
    if ks < 5:    reasons.append(f"kSQI {ks:.1f} < 5 (noise-like)")
    if ps < 0.10: reasons.append(f"pSQI {ps:.3f} < 0.10 (little QRS-band energy)")
    if reasons:
        print("  NOT usable for validation: " + "; ".join(reasons))
    else:
        print("  usable: clean sample stream, QRS-band energy and peakiness present")

if args.plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    show = int(min(n, 10 * args.fs))
    t = np.arange(show) / args.fs
    fig, ax = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    ax[0].plot(t, value[:show], lw=.6, color="#888"); ax[0].set_ylabel("raw (counts)")
    ax[1].plot(t, ecg[:show], lw=.8, color="#c0392b"); ax[1].set_ylabel("filtered")
    if len(rp_a):
        p = rp_a[rp_a < show]
        ax[1].plot(p/args.fs, ecg[p], "o", ms=4, color="#2c3e50", label=f"{len(p)} R-peaks")
        ax[1].legend(loc="upper right")
    ax[1].set_xlabel("seconds")
    ax[0].set_title(f"{path.name} - first {show/args.fs:.0f}s")
    out = path.with_suffix(".png")
    fig.tight_layout(); fig.savefig(out, dpi=110)
    print(f"\n  plot -> {out}")
