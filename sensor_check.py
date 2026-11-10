#!/usr/bin/env python3
"""Bench checks for the extra sensors: is each stream alive and responding?

    ./sensor_check.py captures/<stamp>_<label>_ref.csv [--checks imu,temp] [--taps 5] [--breath 30]

Give it the ECG CSV; it loads the sensor files beside it (sensor_streams.py).
Run ./integrity.py on the same capture first: these checks assume the rows
are all there. Saves analysis/sensor_check_<stem>.txt and .png.

One check per sensor (docs/bench_session_1.md, part B):
  IMU          taps on the board show as spikes in |accel|; --taps N says how
               many were made, and the count has to match
  temperature  stable while nothing changes: spread and drift over the capture
  PPG          pulse rate from the PPG against heart rate from the ECG, same window
  GSR          a deep breath at --breath T (seconds into the capture) moves the
               output away from its level in the 10 s before

--checks picks which to run (default: every stream the capture has). Use it
when a capture was made for one sensor, so the others do not print a verdict
on a signal nobody was providing: a PPG with no finger on it will fail.

These are LIVENESS checks with provisional pass marks (below), not validation.
A pass says the sensor is wired, configured and timestamped; it says nothing
about accuracy. The pass marks are proposals, set before any hardware data
existed, and should be revised from the first session's files.
"""
import argparse, pathlib, sys
import numpy as np
from scipy import signal as sps
from pan_tompkins import detect
from sensor_streams import (sidecar, ECG_SPS, GSR_OVERSAMPLE, ACCEL_LSB_PER_G,
                            TEMP_C_PER_LSB, PPG_FULL_SCALE)

# Provisional pass marks.
HR_DIFF_BPM   = 2.0     # |median PPG pulse rate - median ECG heart rate|
TEMP_SD_C     = 0.05    # sd of temperature about its trend line
TEMP_DRIFT    = 0.10    # |slope|, degC per minute
TAP_MIN_G     = 0.05    # a tap is at least this far from the resting |accel| ...
TAP_MAD       = 8.0     # ... and at least this many robust sd
TAP_SEP_S     = 0.3     # spikes closer than this are one tap
GSR_MIN_MV    = 5.0     # the breath response is at least this large ...
GSR_NOISE     = 5.0     # ... and this many robust sd of the 10 s before it

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("--checks", default="imu,temp,ppg,gsr", help="comma-separated: imu,temp,ppg,gsr")
ap.add_argument("--taps", type=int, help="number of taps made on the board")
ap.add_argument("--breath", type=float, help="time of the deep breath, seconds into the capture")
ap.add_argument("--mains", type=float, default=50.0)
args = ap.parse_args()

checks = {c.strip() for c in args.checks.split(",")}
unknown = checks - {"imu", "temp", "ppg", "gsr"}
if unknown:
    ap.error(f"unknown check(s): {', '.join(sorted(unknown))}")
out_lines = []
def say(s=""):
    print(s); out_lines.append(s)

def verdict(ok):
    return "PASS" if ok else "FAIL"

def load(path):
    return np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                         invalid_raise=False)

ecg_path = pathlib.Path(args.csv)
ecg = load(ecg_path)
e_idx = ecg["index"].astype(np.int64)
e_us = ecg["isr_micros"].astype(np.int64)
idx0 = int(e_idx[0])
us_of = dict(zip(e_idx.tolist(), e_us.tolist()))

def ecg_time(rows):
    """Seconds on the ECG clock, from the capture's first ECG sample: the
    stamped ecg_index, moved on by how long after that sample's interrupt the
    reading was taken (both micros values are the same ESP32 clock)."""
    idx = rows["ecg_index"].astype(np.int64)
    us = rows["micros"].astype(np.int64)
    ref = np.array([us_of.get(int(i), -1) for i in idx], dtype=np.int64)
    lag = np.where(ref >= 0, ((us - ref + 2**31) % 2**32 - 2**31) / 1e6, 0.0)
    return (idx - idx0) / ECG_SPS + lag

say(f"# ./sensor_check.py {' '.join(sys.argv[1:])}")
say(f"# liveness checks with provisional pass marks; not validation")
say(f"{ecg_path.name}: ECG index {e_idx[0]}..{e_idx[-1]}, {(e_idx[-1]-e_idx[0])/ECG_SPS:.1f} s")
plots = {}

# ------------------------------------------------------------------ ECG beats
breaks = np.flatnonzero(np.diff(e_idx) != 1) + 1
run = max(np.split(np.arange(len(e_idx)), breaks), key=len)
x = ecg["value"].astype(float)[run]
y = sps.sosfiltfilt(sps.butter(4, 0.5, "highpass", fs=ECG_SPS, output="sos"), x)
for f in (args.mains, 2 * args.mains):
    if f < ECG_SPS / 2:
        y = sps.filtfilt(*sps.iirnotch(f, 30.0, fs=ECG_SPS), y)
y = sps.sosfiltfilt(sps.butter(4, 40.0, "lowpass", fs=ECG_SPS, output="sos"), y)
t_run0 = (e_idx[run][0] - idx0) / ECG_SPS
beats = detect(y, ECG_SPS) / ECG_SPS + t_run0           # seconds on the ECG clock
plots["ecg"] = (np.arange(len(y)) / ECG_SPS + t_run0, y, beats)

# ------------------------------------------------------------------ IMU
p = sidecar(ecg_path, "imu")
if "imu" in checks and p.exists():
    m = load(p)
    t = ecg_time(m)
    mag = np.sqrt(m["ax"].astype(float)**2 + m["ay"].astype(float)**2 + m["az"].astype(float)**2) / ACCEL_LSB_PER_G
    rest = np.median(mag)
    dev = np.abs(mag - rest)
    sd = 1.4826 * np.median(dev)
    thr = max(TAP_MIN_G, TAP_MAD * sd)
    hits = np.flatnonzero(dev > thr)
    taps = []
    for i in hits:
        if taps and t[i] - taps[-1][-1][0] <= TAP_SEP_S:
            taps[-1].append((t[i], dev[i]))
        else:
            taps.append([(t[i], dev[i])])
    tap_t = [max(g, key=lambda q: q[1])[0] for g in taps]
    tap_a = [max(q[1] for q in g) for g in taps]
    say(f"\nIMU ({p.name}, {len(mag)} readings)")
    say(f"  |accel| at rest: median {rest:.3f} g, robust sd {sd*1000:.1f} mg; tap threshold {thr*1000:.0f} mg")
    say(f"  spikes found: {len(tap_t)}" + (f" at {', '.join(f'{v:.1f}' for v in tap_t)} s, "
        f"sizes {', '.join(f'{v*1000:.0f}' for v in tap_a)} mg" if tap_t else ""))
    if args.taps is not None:
        say(f"  {verdict(len(tap_t) == args.taps)}: {len(tap_t)} spikes for {args.taps} taps made")
    else:
        say("  no verdict: pass --taps N with the number of taps made")
    plots["imu"] = (t, mag, tap_t, thr, rest)

# ------------------------------------------------------------------ temperature
p = sidecar(ecg_path, "temp")
if "temp" in checks and p.exists():
    m = load(p)
    t = np.atleast_1d(ecg_time(m)); c = np.atleast_1d(m["raw"]).astype(float) * TEMP_C_PER_LSB
    say(f"\nTemperature ({p.name}, {len(c)} readings)")
    if len(c) >= 10:
        slope, icpt = np.polyfit(t, c, 1)
        resid = c - (slope * t + icpt)
        ok = resid.std() <= TEMP_SD_C and abs(slope * 60) <= TEMP_DRIFT
        say(f"  {c.min():.3f}..{c.max():.3f} degC, median {np.median(c):.3f}; "
            f"drift {slope*60:+.3f} degC/min, sd about the trend {resid.std():.4f} degC")
        say(f"  {verdict(ok)}: sd <= {TEMP_SD_C} degC and |drift| <= {TEMP_DRIFT} degC/min "
            f"(uncalibrated: continuous conversion self-heats, see docs/sensor_datasheet_check.md)")
    else:
        say("  fewer than 10 readings: no verdict")
    plots["temp"] = (t, c)

# ------------------------------------------------------------------ PPG
p = sidecar(ecg_path, "ppg")
if "ppg" in checks and p.exists():
    m = load(p)
    pi = m["ppg_index"].astype(np.int64)
    t_poll = ecg_time(m)
    # The poll time is an upper bound on when a sample was taken. The MAX30102
    # clock is steady, so sample time is a straight line in ppg_index, and the
    # line lies along the EARLIEST polls: fit the slope, then drop the line
    # until no poll is earlier than it.
    b, a = np.polyfit(pi, t_poll, 1)
    a += np.min(t_poll - (a + b * pi))
    fs_ppg = 1.0 / b
    full = np.arange(pi[0], pi[-1] + 1)
    ir = np.interp(full, pi, m["ir"].astype(float))
    red = np.interp(full, pi, m["red"].astype(float))
    t_ppg = a + b * full
    bp = sps.butter(2, [0.5, 4.0], "bandpass", fs=fs_ppg, output="sos")
    ac = sps.sosfiltfilt(bp, ir)
    amp = np.percentile(ac, 90) - np.percentile(ac, 10)
    pk, _ = sps.find_peaks(-ac, distance=max(1, int(0.33 * fs_ppg)), prominence=0.3 * amp)
    pulses = t_ppg[pk]
    say(f"\nPPG ({p.name}, {len(pi)} samples)")
    say(f"  MAX30102 sample rate against the ECG clock: {fs_ppg:.3f} per second (set to 100)")
    say(f"  IR  median {np.median(ir):.0f}, pulsatile part (10th-90th pct) {amp:.0f} counts = "
        f"{100*amp/np.median(ir):.2f}% of the level; at full scale {int(np.sum(m['ir'] >= PPG_FULL_SCALE))}")
    say(f"  red median {np.median(red):.0f}; at full scale {int(np.sum(m['red'] >= PPG_FULL_SCALE))}")
    lo, hi = max(beats[0], pulses[0]) if len(beats) and len(pulses) else 0, \
             min(beats[-1], pulses[-1]) if len(beats) and len(pulses) else 0
    eb = beats[(beats >= lo) & (beats <= hi)]; pb = pulses[(pulses >= lo) & (pulses <= hi)]
    if len(eb) >= 10 and len(pb) >= 10:
        hr_e, hr_p = 60 / np.median(np.diff(eb)), 60 / np.median(np.diff(pb))
        say(f"  common window {lo:.1f}..{hi:.1f} s: ECG {len(eb)} beats, median {hr_e:.1f} bpm; "
            f"PPG {len(pb)} pulses, median {hr_p:.1f} bpm; difference {hr_p - hr_e:+.2f} bpm")
        say(f"  {verdict(abs(hr_p - hr_e) <= HR_DIFF_BPM)}: |difference| <= {HR_DIFF_BPM} bpm "
            f"(pulse detection here is a plain peak finder, not the validated detector)")
    else:
        say(f"  FAIL: too few beats in a common window (ECG {len(eb)}, PPG {len(pb)}) to compare rates")
    plots["ppg"] = (t_ppg, ac, pulses)

# ------------------------------------------------------------------ GSR
p = sidecar(ecg_path, "gsr")
if "gsr" in checks and p.exists():
    m = load(p)
    t = ecg_time(m); mv = m["mv_sum"].astype(float) / GSR_OVERSAMPLE
    say(f"\nGSR ({p.name}, {len(mv)} readings)")
    say(f"  output {mv.min():.1f}..{mv.max():.1f} mV, median {np.median(mv):.1f} mV")
    if args.breath is not None:
        pre = mv[(t >= args.breath - 10) & (t < args.breath)]
        post_sel = (t >= args.breath) & (t <= args.breath + 15)
        if len(pre) >= 20 and post_sel.sum() >= 20:
            base = np.median(pre)
            noise = 1.4826 * np.median(np.abs(pre - base))
            d = mv[post_sel] - base
            k = int(np.argmax(np.abs(d)))
            ok = abs(d[k]) >= GSR_MIN_MV and abs(d[k]) >= GSR_NOISE * noise
            say(f"  10 s before the breath at {args.breath:.0f} s: {base:.1f} mV, robust sd {noise:.2f} mV")
            say(f"  largest move in the 15 s after: {d[k]:+.1f} mV, {t[post_sel][k]-args.breath:.1f} s after the breath")
            say(f"  {verdict(ok)}: |move| >= {GSR_MIN_MV} mV and >= {GSR_NOISE:g} x the sd before. "
                f"Read from the schematic, a rise in skin conductance LOWERS this voltage "
                f"(docs/sensor_inventory.md); the sign seen here is the first measurement of that.")
        else:
            say("  no verdict: not enough readings around --breath")
    else:
        say("  no verdict: pass --breath T with the time of the deep breath")
    plots["gsr"] = (t, mv)

# ------------------------------------------------------------------ save
stem = ecg_path.stem
pathlib.Path("analysis").mkdir(exist_ok=True)
txt = pathlib.Path("analysis") / f"sensor_check_{stem}.txt"
txt.write_text("\n".join(out_lines) + "\n")
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = [k for k in ("ecg", "ppg", "gsr", "temp", "imu") if k in plots]
    fig, axes = plt.subplots(len(order), 1, figsize=(12, 2.2 * len(order)), sharex=True)
    for ax, k in zip(np.atleast_1d(axes), order):
        if k == "ecg":
            tt, yy, bb = plots[k]; ax.plot(tt, yy, lw=0.6, color="#1f6f8b")
            ax.plot(bb, np.interp(bb, tt, yy), ".", ms=4, color="#c0392b"); ax.set_ylabel("ECG (counts)")
        elif k == "ppg":
            tt, yy, bb = plots[k]; ax.plot(tt, yy, lw=0.7, color="#7d3c98")
            ax.plot(bb, np.interp(bb, tt, yy), ".", ms=4, color="#c0392b"); ax.set_ylabel("PPG IR, 0.5-4 Hz")
        elif k == "gsr":
            ax.plot(*plots[k], lw=0.8, color="#1e8449"); ax.set_ylabel("GSR out (mV)")
            if args.breath is not None: ax.axvline(args.breath, color="k", ls=":", lw=0.8)
        elif k == "temp":
            ax.plot(*plots[k], ".-", lw=0.8, ms=3, color="#b9770e"); ax.set_ylabel("temp (degC)")
        elif k == "imu":
            tt, yy, bb, thr, rest = plots[k]; ax.plot(tt, yy, lw=0.6, color="#34495e")
            for v in bb: ax.axvline(v, color="#c0392b", lw=0.6)
            ax.axhline(rest + thr, color="k", ls=":", lw=0.6); ax.set_ylabel("|accel| (g)")
        ax.grid(alpha=0.3)
    np.atleast_1d(axes)[-1].set_xlabel("seconds on the ECG clock, from the capture's first sample")
    fig.suptitle(f"{ecg_path.name}: liveness checks, not validation", fontsize=10)
    fig.tight_layout()
    png = txt.with_suffix(".png"); fig.savefig(png, dpi=110)
    print(f"saved {txt} and {png}")
except Exception as e:                                   # the numbers matter more than the picture
    print(f"saved {txt} (no plot: {e})")
