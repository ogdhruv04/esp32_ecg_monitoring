#!/usr/bin/env python3
"""Write fixtures for BeatDetectorParityTest (android_app/.../src/test).

BeatDetector.kt must find exactly the beats pan_tompkins.py finds, at the same
positions (tp3), with the same flags and the same HRV (CLAUDE.md). This runs the
Python detector over real recordings and saves its input and its outputs; the
Kotlin test feeds the same input and compares. Re-run this whenever
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

def run(x, skips, stall=True, timing=None):
    """What BeatDetector.kt emits on the phone: (position, flagged) for every
    beat process() returns, and the detector, for its HRV history.

    Not pt.peaks: that offline list also keeps beats found during the 2 s
    warm-up, which the phone deliberately does not show.
    """
    pt = pan_tompkins.PanTompkins(FS, timing)   # None = the shipped timing point (tp3)
    if not stall:
        pt.stall = 10**12                      # the detector before the fix
    out = []
    for i, v in enumerate(x):
        if skips[i]:
            pt.skip(int(skips[i]))
        r = pt.process(float(v))
        if r is not None:
            out.append((r, pt.beats[-1]["flagged"]))   # the beat just located
    return out, pt

def write(name, x, skips, beats, pt):
    """Input; expected beats as `position,flagged`; expected HRV as
    `rmssd,accepted,dropped,coverage` (rmssd 'nan' when the phone would show
    none), computed by pan_tompkins.rr_history + rmssd_nn - the reference for
    BeatDetector.rmssdMs, nnDropped and hrvCoverage."""
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}_input.csv", "w") as f:
        f.write("value,skip_before\n")
        for v, s in zip(x, skips):
            f.write(f"{repr(float(v))},{int(s)}\n")
    (OUT / f"{name}_expected.txt").write_text(
        "".join(f"{p!r},{int(fl)}\n" for p, fl in beats))
    rm, acc, drop, cov = pan_tompkins.rmssd_nn(pan_tompkins.rr_history(pt.beats, FS))
    (OUT / f"{name}_rmssd.txt").write_text(
        f"{(rm if rm is not None else float('nan'))!r},{acc},{drop},{cov!r}\n")
    return rm, acc, drop, cov

def mistimed(flipped_pt, unflipped_pt, t0):
    """Beats after t0 in the flipped run that are NOT flagged yet sit >= 1 sample
    from the same beat (same 5-15 Hz index) in the unflipped run. The flipped
    input is exactly the negated filtered signal, so a correctly timed beat lands
    on the identical position. Returns (beats after t0, flagged, mistimed)."""
    ref = {b["bp"]: b["pos"] for b in unflipped_pt.beats}
    after = [b for b in flipped_pt.beats if b["bp"] >= t0]
    off = np.array([b["pos"] - ref[b["bp"]] for b in after if not b["flagged"] and b["bp"] in ref])
    mis = int(np.sum(np.abs(off) >= 1.0))
    # tp3 refers the time to one followed peak of the median beat; after a flip
    # that can be another lobe, which moves every later beat by the same amount.
    # What matters for RR is how much that offset varies from beat to beat.
    spread = (float(np.median(off)) * 1000 / FS, float(np.std(off)) * 1000 / FS) if len(off) else (float("nan"),) * 2
    return len(after), sum(b["flagged"] for b in after), mis, spread

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

# Polarity case: the finger recording with its sign inverted from 30 s on. The
# rolling median beat passes through undecided (beats flagged, fallback
# position, kept out of HRV) and settles on the other sign - the path that
# matters on ambiguous morphology such as MIT-BIH 108. Built from our own data,
# so the test needs no external dataset.
flip = finger[: int(60 * FS)].copy()
flip[int(30 * FS):] *= -1
cases["polarity_flip"] = (flip, np.zeros(len(flip), int))

for name, (x, s) in cases.items():
    beats, pt = run(x, s)
    rm, acc, drop, cov = write(name, x, s, beats, pt)
    after = sum(1 for p, _ in beats if p > (11.5 * FS))
    line = (f"{name:14} {len(x):6d} samples  {len(beats):4d} beats, {sum(f for _, f in beats)} flagged "
            f"(followed peak picked again {pt.repicked}x); RMSSD {rm if rm is None else round(rm, 2)} ms, "
            f"coverage {100*cov:.0f}% ({acc} NN), {drop} dropped")
    if name == "artifact_gaps":
        old, _ = run(x, s, stall=False)
        old_after = sum(1 for p, _ in old if p > (11.5 * FS))
        line += (f"   beats after the artifact: {after} with stall decay, "
                 f"{old_after} without")
    print(line)
    if name == "polarity_flip":
        unflipped = finger[: int(60 * FS)]
        z = np.zeros(len(unflipped), int)
        for timing in ("tp2.1", "tp3"):
            _, pf = run(x, s, timing=timing); _, pu = run(unflipped, z, timing=timing)
            n, fl, mis, (om, osd) = mistimed(pf, pu, int(30 * FS))
            rmf = pan_tompkins.rmssd_nn(pan_tompkins.rr_history(pf.beats, FS))
            rmu = pan_tompkins.rmssd_nn(pan_tompkins.rr_history(pu.beats, FS))
            print(f"{'':14} {timing:5}: after the flip {n} beats, {fl} flagged, "
                  f"{mis} a sample or more from the unflipped run (offset median {om:+.1f} ms, sd {osd:.2f} ms); "
                  f"RMSSD {rmf[0]:.2f} ms (coverage {100*rmf[3]:.0f}%) vs "
                  f"{rmu[0]:.2f} ms unflipped (coverage {100*rmu[3]:.0f}%)")
print(f"wrote {OUT}/")
