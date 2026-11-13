#!/usr/bin/env python3
"""Independent reference for the phone's live heart rate (LiveHeartRateTest).

The live rate on the main, recording and guided-breathing screens is computed
from the streaming detector's beats as they arrive. To check it we need a rate
for every moment of a replay that does not come from that detector: here the
whole capture is filtered zero-phase (as agreement.py does) and its R peaks are
found offline by NeuroKit2 (method "neurokit"), a different detector.

Reference rate at time t: the intervals between consecutive reference peaks
whose later peak lies in (t - 10 s, t], leaving out any interval that spans
lost samples. The window counts as clean only if it holds at least 5 intervals,
all within 300-2000 ms and each within 20% of the interval before it (a
heart rate changes gradually from beat to beat; a missed or extra beat does
not); then the reference is 60000 / median. Otherwise there is no reference at t (artifact, a missed
beat, a gap). A loose reference is also written: 60000 / median of the
intervals of the window that pass both tests, when at least 5 do, so that one
ectopic beat does not leave 10 s unchecked. The window and the 300-2000 ms / 20% tests are the live rule's
(LiveHeartRate.kt), which reuses the NN-cleaning bounds of pan_tompkins.clean_nn.

Times are seconds from the first sample of the capture, the origin
CaptureReplay.kt counts packets from.

Writes android_app/app/src/test/resources/livehr/<case>_reference.tsv and
analysis/app_live_hr_reference.txt.
"""
import pathlib

import neurokit2 as nk
import numpy as np
import scipy.signal as sps

FS = 256.0
MAINS = 50.0
WINDOW_S = 10.0
MIN_INTERVALS = 5
NN_MIN_MS, NN_MAX_MS, NN_STEP = 300.0, 2000.0, 0.20
STEP_S = 0.25

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "android_app/app/src/test/resources/livehr"
CASES = {
    "tb02": "captures/20261027_174352_testboard02.csv",
    "dual03_ring": "captures/20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv",
}


def load(path):
    """Received samples on the capture's index timeline (offset from the first
    sample with a value, ETAG 6/7 dropped, duplicates dropped) and a mask of
    the offsets that never arrived."""
    raw = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8", invalid_raise=False)
    idx = raw["index"].astype(np.int64)
    val = raw["value"].astype(float)
    etag = raw["etag"].astype(np.int64)
    keep = ~np.isin(etag, [6, 7])
    idx, val = idx[keep], val[keep]
    off = idx - idx[0]
    _, first = np.unique(off, return_index=True)
    off, val = off[first], val[first]
    n = int(off[-1]) + 1
    lost = np.ones(n, bool); lost[off] = False
    x = np.interp(np.arange(n), off, val)      # only to keep the filters fed across holes
    return x, lost


def zero_phase(x):
    y = sps.sosfiltfilt(sps.butter(4, 0.5, "highpass", fs=FS, output="sos"), x)
    for f in (MAINS, 2 * MAINS):
        b, a = sps.iirnotch(f, 30.0, fs=FS); y = sps.filtfilt(b, a, y)
    return sps.sosfiltfilt(sps.butter(4, 40.0, "lowpass", fs=FS, output="sos"), y)


def reference(peaks, lost, t_end):
    cum = np.concatenate([[0], np.cumsum(lost)])
    # (end time s, interval ms, good): good = in range and within NN_STEP of the
    # interval just before it, which must exist and be gap-free too.
    iv = []
    prev = None
    for a, b in zip(peaks[:-1], peaks[1:]):
        if cum[b + 1] - cum[a] != 0:
            prev = None
            continue
        ms = 1000.0 * (b - a) / FS
        good = NN_MIN_MS <= ms <= NN_MAX_MS and prev is not None and abs(ms - prev) <= NN_STEP * prev
        iv.append((b / FS, ms, good))
        prev = ms
    iv = np.array(iv, dtype=float)
    rows = []
    for t in np.arange(0.0, t_end + 1e-9, STEP_S):
        sel = iv[(iv[:, 0] > t - WINDOW_S) & (iv[:, 0] <= t)] if len(iv) else np.zeros((0, 3))
        ref = loose = None
        if len(sel) >= MIN_INTERVALS and np.all(sel[:, 2] > 0):
            ref = 60000.0 / float(np.median(sel[:, 1]))
        ok = sel[sel[:, 2] > 0, 1]
        if len(ok) >= MIN_INTERVALS:
            loose = 60000.0 / float(np.median(ok))
        rows.append((t, ref, loose))
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# Live heart-rate reference (make_live_hr_fixtures.py): zero-phase filter, NeuroKit2 "
             f"{nk.__version__} ecg_peaks(method='neurokit'); window {WINDOW_S:g} s, >= {MIN_INTERVALS} intervals, "
             f"all {NN_MIN_MS:g}-{NN_MAX_MS:g} ms and each within {100 * NN_STEP:g}% of the one before."]
    for name, rel in CASES.items():
        x, lost = load(ROOT / rel)
        y = zero_phase(x)
        _, info = nk.ecg_peaks(y, sampling_rate=FS, method="neurokit")
        peaks = np.asarray(info["ECG_R_Peaks"], dtype=np.int64)
        rows = reference(peaks, lost, (len(x) - 1) / FS)
        with open(OUT / f"{name}_reference.tsv", "w") as f:
            f.write("t_s\tref_bpm\tloose_bpm\n")
            for t, r, lo in rows:
                f.write(f"{t:.2f}\t{'' if r is None else repr(r)}\t{'' if lo is None else repr(lo)}\n")
        refs = np.array([r for _, r, _ in rows if r is not None])
        nloose = sum(1 for _, r, lo in rows if r is None and lo is not None)
        lines.append(f"{name:12} {rel}: {len(x) / FS:.1f} s, {int(lost.sum())} samples lost, {len(peaks)} reference peaks; "
                     f"reference defined at {len(refs)}/{len(rows)} moments ({100 * len(refs) / len(rows):.1f}%), "
                     f"{refs.min():.1f}-{refs.max():.1f} bpm, median {np.median(refs):.1f}; loose reference only at {nloose} more")
        # Where the reference says the rate moved: the 10 s windows at their extremes.
        hi = max((r, t) for t, r, _ in rows if r is not None)
        lo = min((r, t) for t, r, _ in rows if r is not None)
        lines.append(f"{'':12} highest {hi[0]:.1f} bpm at {hi[1]:.2f} s, lowest {lo[0]:.1f} bpm at {lo[1]:.2f} s; "
                     f"first defined at {next(t for t, r, _ in rows if r is not None):.2f} s")
    (ROOT / "analysis/app_live_hr_reference.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
