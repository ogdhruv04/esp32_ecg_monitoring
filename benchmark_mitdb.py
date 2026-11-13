#!/usr/bin/env python3
"""Benchmark the R-peak detector against MIT-BIH expert annotations, per ANSI/AAMI EC57.

    ./benchmark_mitdb.py

Reports sensitivity and positive predictivity per record. Deliberately NOT
"accuracy": with ~1% prevalence of anything interesting, a detector that finds
nothing still scores well on accuracy. EC57 asks for Se and P+ separately, and
so does any reviewer who knows the field.

This validates the CODE, not the hardware. MIT-BIH uses chest electrodes on
different bodies with different noise; it cannot tell us whether our ring
captures real cardiac activity. Only a simultaneous reference recording does
that. Two different questions, two different ground truths.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs under python -I
import numpy as np
import wfdb
from scipy import signal as sps

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="data/mitdb")
ap.add_argument("--records", nargs="*", help="records to use (default: every .hea in --dir)")
ap.add_argument("--lead", choices=["0", "mlii"], default="0",
                help="channel 0 (default, as the dev results), or MLII where the record has it "
                     "(the held-out protocol in tp2_config.json)")
ap.add_argument("--timing", choices=["tp3", "tp2.1"], default="tp3",
                help="method ours: the shipped timing point (tp3) or the previous one")
ap.add_argument("--check", choices=["on", "off"], default="on",
                help="method ours with --timing tp2.1: its per-beat correlation check on (tp2.1) or off (tp2)")
ap.add_argument("--positions", choices=["tp2", "bp"], default="tp2",
                help="method ours: score tp2 positions (default) or the 5-15 Hz peak "
                     "(tp1 location, with the 23 Oct search-back fix) - for attribution")
ap.add_argument("--fs-target", type=float, default=None,
                help="resample to this rate first (e.g. 256 to match our device)")
ap.add_argument("--method", default="neurokit")
ap.add_argument("--tolerance-ms", type=float, default=150.0)
ap.add_argument("--sqi-gate", type=float, default=None,
                help="reject windows below this bSQI (0-1), e.g. 0.9")
ap.add_argument("--window-s", type=float, default=10.0)
args = ap.parse_args()

import neurokit2 as nk

# MIT-BIH beat-annotation symbols. Everything else (rhythm markers, signal
# quality flags, paced-rhythm notes) is not a beat and must not count as a miss.
BEAT_SYMS = set("NLRejAaJSVEFP/fQ")

def filter_chain(x, fs, mains=60.0):
    # MIT-BIH was recorded in the US: mains is 60 Hz there, not the 50 Hz we
    # notch on our own bench. Getting this backwards would leave the interference
    # in and notch a clean band instead.
    sos = sps.butter(4, 0.5, "highpass", fs=fs, output="sos")
    y = sps.sosfiltfilt(sos, x)
    b, a = sps.iirnotch(mains, 30.0, fs=fs); y = sps.filtfilt(b, a, y)
    sos = sps.butter(4, 40.0, "lowpass", fs=fs, output="sos")
    return sps.sosfiltfilt(sos, y)

def evaluate(ref, test, tol):
    """Greedy nearest-match within tol samples; each reference beat used once."""
    ref = np.sort(np.asarray(ref)); test = np.sort(np.asarray(test))
    used = np.zeros(len(ref), bool)
    tp = 0
    for t in test:
        i = np.searchsorted(ref, t)
        best, bestd = -1, tol + 1
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(ref) and not used[j]:
                d = abs(ref[j] - t)
                if d < bestd: best, bestd = j, d
        if best >= 0 and bestd <= tol:
            used[best] = True; tp += 1
    fp = len(test) - tp
    fn = len(ref) - tp
    return tp, fp, fn

import pathlib
recs = args.records or sorted(p.stem for p in pathlib.Path(args.dir).glob("*.hea"))
if not recs:
    sys.exit(f"no records in {args.dir}")

label = f"{args.fs_target:g} Hz (resampled)" if args.fs_target else "native 360 Hz"
print(f"\nANSI/AAMI EC57 QRS detection - {len(recs)} records, {label}, "
      f"method={args.method}, tolerance={args.tolerance_ms:g} ms")
if args.method == "ours":
    import pan_tompkins
    tp = (args.timing if args.check == "on" or args.timing == "tp3" else "tp2 (correlation check off)") \
        if args.positions == "tp2" else "bp (5-15 Hz peak, search-back fixed)"
    print(f"timing point: {tp} (pan_tompkins.py, tp2_config.json); lead: "
          f"{'MLII where present, else channel 0' if args.lead == 'mlii' else 'channel 0'}")
print()
print(f"{'rec':>5} {'beats':>7} {'TP':>7} {'FP':>6} {'FN':>6} {'Se%':>7} {'P+%':>7}")
print("-" * 50)

TP = FP = FN = 0
rows = []
REJ = []
for rec in recs:
    r = wfdb.rdrecord(f"{args.dir}/{rec}")
    ann = wfdb.rdann(f"{args.dir}/{rec}", "atr")
    fs = float(r.fs)
    ch = list(r.sig_name).index("MLII") if args.lead == "mlii" and "MLII" in r.sig_name else 0
    x = r.p_signal[:, ch].astype(float)

    ref = np.array([s for s, sym in zip(ann.sample, ann.symbol) if sym in BEAT_SYMS])

    if args.fs_target and args.fs_target != fs:
        n_new = int(round(len(x) * args.fs_target / fs))
        x = sps.resample(x, n_new)
        ref = np.round(ref * args.fs_target / fs).astype(int)
        fs = args.fs_target

    y = filter_chain(x, fs)
    if args.method == "ours":
        import pan_tompkins
        if args.positions == "bp":
            pt = pan_tompkins.PanTompkins(fs, timing=args.timing)
            for v in y: pt.process(v)
            test = np.array(pt.bp_peaks, dtype=int)
        else:
            pt = pan_tompkins.PanTompkins(fs, timing=args.timing)
            if args.check == "off":
                pt.CORR_MIN = None
            for v in y: pt.process(v)
            test = np.array(pt.peaks, dtype=float)
    else:
        _, info = nk.ecg_peaks(y, sampling_rate=fs, method=args.method)
        test = np.asarray(info["ECG_R_Peaks"], dtype=int)

    tol = int(round(args.tolerance_ms / 1000.0 * fs))

    if args.sqi_gate is not None:
        # bSQI: run a second, independent detector and measure agreement. Two
        # detectors converge on real beats and diverge on noise, so disagreement
        # localises unreliable stretches WITHOUT needing the reference
        # annotations - which is what makes it usable on our own recordings,
        # where no annotations exist. Reject those windows and report how much
        # was thrown away alongside the accuracy gained; accuracy on a
        # hand-picked subset is not a result.
        _, info2 = nk.ecg_peaks(y, sampling_rate=fs, method="pantompkins1985")
        alt = np.asarray(info2["ECG_R_Peaks"], dtype=int)
        wlen = int(args.window_s * fs)
        keep = np.zeros(len(y), bool)
        for start in range(0, len(y), wlen):
            end = min(start + wlen, len(y))
            a = test[(test >= start) & (test < end)]
            b = alt[(alt >= start) & (alt < end)]
            if len(a) == 0 and len(b) == 0:
                continue
            m = sum(1 for p in a if len(b) and np.min(np.abs(b - p)) <= tol)
            union = len(a) + len(b) - m
            if union and m / union >= args.sqi_gate:
                keep[start:end] = True
        rejected_frac = 1.0 - keep.mean()
        ref = ref[keep[np.clip(ref, 0, len(y) - 1)]]
        # Our positions are fractional (tp2); round only to look up the window.
        test = test[keep[np.clip(np.round(test).astype(int), 0, len(y) - 1)]]
        REJ.append(rejected_frac)

    tp, fp, fn = evaluate(ref, test, tol)
    se = 100.0 * tp / (tp + fn) if tp + fn else 0.0
    pp = 100.0 * tp / (tp + fp) if tp + fp else 0.0
    TP += tp; FP += fp; FN += fn
    rows.append((rec, se, pp))
    print(f"{rec:>5} {len(ref):7d} {tp:7d} {fp:6d} {fn:6d} {se:7.2f} {pp:7.2f}")

SE = 100.0 * TP / (TP + FN) if TP + FN else 0.0
PP = 100.0 * TP / (TP + FP) if TP + FP else 0.0
print("-" * 50)
print(f"{'ALL':>5} {TP+FN:7d} {TP:7d} {FP:6d} {FN:6d} {SE:7.2f} {PP:7.2f}")

print(f"\ngross Se {SE:.2f}%   gross P+ {PP:.2f}%")
if REJ:
    print(f"data rejected by SQI gate (bSQI < {args.sqi_gate:g}): "
          f"{100*np.mean(REJ):.1f}% of recording time")
gate = SE >= 99.0 and PP >= 99.0
print(f"Week 3 gate (Se >= 99% AND P+ >= 99%): {'PASS' if gate else 'FAIL'}")
worst = sorted(rows, key=lambda t: min(t[1], t[2]))[:3]
print("worst records: " + ", ".join(f"{r} (Se {s:.1f}, P+ {p:.1f})" for r, s, p in worst))
