#!/usr/bin/env python3
"""Write fixtures for BeatDetectorParityTest (android_app/.../src/test).

BeatDetector.kt must find exactly the beats pan_tompkins.py finds (CLAUDE.md).
This runs the Python detector over real recordings and saves its input and its
beats; the Kotlin test feeds the same input and compares. Re-run this whenever
pan_tompkins.py changes, then run the test:

    ./make_parity_fixtures.py && (cd android_app && ./gradlew testDebugUnitTest)

Inputs are stored as float32, because the phone feeds the detector Floats. The
Python side processes those same float32 values, so both compute in double
precision from identical numbers.

Fixture format, one row per sample:  value,skip_before
skip_before > 0 means detector.skip(n) is called before that sample is fed.
"""
import pathlib
import numpy as np
from scipy import signal as sps
import pan_tompkins

FS = 256.0
OUT = pathlib.Path("android_app/app/src/test/resources/parity")
CAP = "captures/20260929_163314_dual03_both3wire_c3chest_wroomfinger"

def causal_filter(x):
    """Approximates EcgFilter.kt: 0.5 Hz HP, 50/100 Hz notch, 40 Hz LP, causal."""
    y = sps.sosfilt(sps.butter(4, 0.5, "highpass", fs=FS, output="sos"), x)
    for f in (50.0, 100.0):
        b, a = sps.iirnotch(f, 30.0, fs=FS); y = sps.lfilter(b, a, y)
    return sps.sosfilt(sps.butter(4, 40.0, "lowpass", fs=FS, output="sos"), y)

def load(path, seconds):
    v = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                      invalid_raise=False)["value"].astype(float)
    return causal_filter(v)[: int(seconds * FS)].astype(np.float32)

def run(x, skips, stall=True):
    """The beats process() returns - what BeatDetector.kt emits on the phone.

    Not pt.peaks: that offline list also keeps beats found during the 2 s
    warm-up, which the phone deliberately does not show.
    """
    pt = pan_tompkins.PanTompkins(FS)
    if not stall:
        pt.stall = 10**12                      # the detector before the fix
    out = []
    for i, v in enumerate(x):
        if skips[i]:
            pt.skip(int(skips[i]))
        r = pt.process(float(v))
        if r is not None:
            out.append(r)
    return out

def phone_rmssd(x, skips):
    """RMSSD by the phone's rules (BeatDetector.rrHist / rmssdMs), in ms.

    Intervals between consecutive primary detections' refined R-peaks; a
    search-back beat or a lost-data gap breaks the series; intervals outside
    300-2000 ms and successive differences over 300 ms are left out. Python's
    detector has no HRV of its own, so this is the reference the Kotlin HRV
    path is held to.
    """
    pt = pan_tompkins.PanTompkins(FS)
    sb = {"hit": False}
    orig = pt._search_back
    def flagged():
        r = orig()
        if r is not None:
            sb["hit"] = True
        return r
    pt._search_back = flagged
    # Every accepted beat lands in pt.peaks, including those in the warm-up,
    # which the phone also feeds into rrHist (it only hides them from display).
    # At most one beat is accepted per sample.
    hist, last_r, gap = [], None, False
    for i, v in enumerate(x):
        if skips[i]:
            pt.skip(int(skips[i])); gap = True
        sb["hit"] = False
        before = len(pt.peaks)
        pt.process(float(v))
        if len(pt.peaks) == before:
            continue
        r = pt.peaks[-1]
        if sb["hit"]:
            if last_r is not None: hist.append(None)
            last_r = None
        else:
            if last_r is not None: hist.append(None if gap else r - last_r)
            last_r = r
        gap = False
    ms = [None if h is None else 1000.0 * h / FS for h in hist]
    ok = lambda m: m is not None and 300.0 <= m <= 2000.0
    d = [ms[i] - ms[i-1] for i in range(1, len(ms))
         if ok(ms[i]) and ok(ms[i-1]) and abs(ms[i] - ms[i-1]) <= 300.0]
    return float(np.sqrt(np.mean(np.square(d)))) if d else float("nan")

def write(name, x, skips, peaks):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}_input.csv", "w") as f:
        f.write("value,skip_before\n")
        for v, s in zip(x, skips):
            f.write(f"{repr(float(v))},{int(s)}\n")
    (OUT / f"{name}_expected.txt").write_text("\n".join(str(p) for p in peaks) + "\n")
    (OUT / f"{name}_rmssd.txt").write_text(f"{phone_rmssd(x, skips)!r}\n")

cases = {}
chest = load(CAP + "_ring.csv", 60)
cases["chest"] = (chest, np.zeros(len(chest), int))
finger = load(CAP + "_ref.csv", 105)
cases["finger"] = (finger, np.zeros(len(finger), int))

# Stress case: a 1.5 s artifact 40x the largest R-peak at 10 s (an electrode
# knock), then lost-packet gaps of 1, 2 and 5 packets (6 samples each).
art = finger[: int(60 * FS)].copy()
a0 = int(10 * FS); n_art = int(1.5 * FS)
art[a0:a0 + n_art] += (40 * np.abs(art).max()
                       * np.sin(np.linspace(0, 3 * np.pi, n_art))).astype(np.float32)
sk = np.zeros(len(art), int)
for t, n in ((20, 6), (30, 12), (45, 30)):
    sk[int(t * FS)] = n
cases["artifact_gaps"] = (art, sk)

for name, (x, s) in cases.items():
    peaks = run(x, s)
    write(name, x, s, peaks)
    after = sum(1 for p in peaks if p > (11.5 * FS))
    line = f"{name:14} {len(x):6d} samples  {len(peaks):4d} beats"
    if name == "artifact_gaps":
        old = run(x, s, stall=False)
        old_after = sum(1 for p in old if p > (11.5 * FS))
        line += (f"   beats after the artifact: {after} with stall decay, "
                 f"{old_after} without")
    print(line)
print(f"wrote {OUT}/")
