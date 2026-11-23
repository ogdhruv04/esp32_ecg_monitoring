#!/usr/bin/env python3
"""Is the wrist BVP read right? A data-format check from the pilot (plan section 10, rule 1).

    ./wesad_pulse_check.py --cache <main>/data/wesad_cache --subjects S2 S3

For each part, the band-passed BVP is averaged around every ECG beat (-0.3 to
+1.0 s). If pulses are locked to beats, the average is a clear pulse whose
peak-to-trough is a large share of the single pulses' median amplitude
(locking ratio near 1); if they are not, it averages out towards 0. The lag of
the average's maximum and of its steepest upstroke say where the systolic peak
and the foot sit after the R wave, and the sign of the average says whether the
signal's polarity is what ppg.detect assumes (systolic peak = maximum).
Saves analysis/wesad_pilot_pulse_shape.txt.
"""
import argparse, io, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from scipy import signal as sps

ap = argparse.ArgumentParser()
ap.add_argument("--cache", required=True)
ap.add_argument("--subjects", nargs="+", required=True)
args = ap.parse_args()

from algorithms import wesad, ppg, frontend
from algorithms.core import CONFIG
W = CONFIG["wesad"]; FSB = W["fs"]["bvp"]
out = io.StringIO(); p = lambda *a: print(*a, file=out)
p("Wrist BVP averaged around chest ECG beats, per part (pilot data-format check, docs/wesad_plan.md section 10 rule 1)")
p("lock = (max - min of the beat-locked average) / median single-pulse amplitude; near 1 = locked, near 0 = not")
p("peak / upstroke = lag after the R wave of the average's maximum / steepest rise; min = lag of its minimum\n")
for s in args.subjects:
    rec = wesad.load(args.cache, s)
    x = sps.resample_poly(rec.ecg.astype(float), 128, 350)
    beats = frontend.detect(frontend.filter_ecg(x, 256.0, W["mains_hz"], causal=True), 256.0)
    bt = np.array([b["pos"] for b in beats]) / 256.0
    y = ppg.bandpass(rec.bvp, FSB)
    pulses = ppg.detect(y, FSB)
    lags = np.arange(int(-0.3 * FSB), int(1.0 * FSB))
    p(f"{s}:")
    for part, (a, b) in rec.parts().items():
        k = bt[(bt >= a + 1) & (bt < b - 2)]
        idx = np.round(k * FSB).astype(int)[:, None] + lags[None, :]
        avg = y[idx].mean(axis=0)
        amp = np.median(pulses.amp[(pulses.t >= a) & (pulses.t < b)])
        d = np.diff(avg)
        p(f"  {part:13s} beats {len(k):5d}  lock {(avg.max() - avg.min()) / amp:5.2f}  "
          f"peak {1000 * lags[np.argmax(avg)] / FSB:+5.0f} ms  min {1000 * lags[np.argmin(avg)] / FSB:+5.0f} ms  "
          f"upstroke {1000 * (lags[np.argmax(d)] + 0.5) / FSB:+5.0f} ms  steepest fall {1000 * (lags[np.argmin(d)] + 0.5) / FSB:+5.0f} ms")
text = out.getvalue(); print(text)
dest = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "analysis" / "wesad_pilot_pulse_shape.txt"
dest.write_text(text); print("saved", dest)
