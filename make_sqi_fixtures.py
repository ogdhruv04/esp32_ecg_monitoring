#!/usr/bin/env python3
"""Fixtures for SignalQualityParityTest: the quality gate on real recordings.

    ./make_sqi_fixtures.py --captures <main>/captures --nst <main>/data/nstdb

Each case is a stretch of display signal and 5-15 Hz signal (float32, as the
phone holds them), fed from its first sample to a fresh gate, and what
signal_quality.py says every 64 samples once 1 s has arrived: kurtosis, band
share, the largest swing ratio, artifact or not, the verdict. The phone's
SignalQuality.kt must give the same.

  tb02_settling   tb02, first 60 s: electrode-settling transients, then clean
  tb01_burst      tb01, 55-110 s: clean, then 16 s of large swings
  dual03_finger   dual03 finger, first 30 s: a clean recording
  nst_118e00      MIT-BIH NST 118e00, 280-320 s: noise at 0 dB starts at 300 s

The filter that made these signals is scipy's (an approximation of
EcgFilter.kt); the test is of the gate, which is handed these exact samples.
Writes android_app/app/src/test/resources/sqi/ and analysis/sqi_fixtures.txt.
"""
import argparse, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import signal_quality as SQ
from algorithms import frontend

ap = argparse.ArgumentParser()
ap.add_argument("--captures", required=True); ap.add_argument("--nst", required=True)
args = ap.parse_args()
HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
OUT = HERE / "android_app/app/src/test/resources/sqi"
FS = frontend.FS


def own(fn):
    val, _, _ = frontend.load_capture(f"{args.captures}/{fn}")
    return frontend.filter_ecg(val, FS, 50.0, causal=True, harmonic=True)


def nst(rec):
    import wfdb
    r = wfdb.rdrecord(f"{args.nst}/{rec}")
    return frontend.filter_ecg(frontend.resample(r.p_signal[:, 0], float(r.fs)), FS, 60.0, causal=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [("tb02_settling", own("20261027_174352_testboard02.csv"), 0, 60),
             ("tb01_burst", own("20261027_173714_testboard01.csv"), 55, 110),
             ("dual03_finger", own("20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv"), 0, 30),
             ("nst_118e00", nst("118e00"), 280, 320)]
    lines = [f"# ./make_sqi_fixtures.py   gate {SQ.VERSION}", ""]
    w = int(SQ.CONFIG["window_s"] * FS)
    for name, f, t0, t1 in cases:
        # display and band signals of the whole recording, then the stretch: the
        # filters before the gate keep their history, the gate starts fresh.
        d = SQ.display_signal(f, FS)[int(t0 * FS):int(t1 * FS)]; q = SQ.qrs_signal(f, FS)[int(t0 * FS):int(t1 * FS)]
        gate = SQ.SignalQuality(FS); rows = []
        for i in range(len(d)):
            gate.track(d[i]); n = i + 1
            if n % SQ.QUALITY_EVERY == 0 and n >= int(FS):
                r = gate.assess(d[max(0, n - w):n], q[max(0, n - w):n])
                rows.append((n, r))
        with open(OUT / f"{name}_input.csv", "w") as fh:
            fh.write("display,qrs\n")
            for a, b in zip(d, q):
                fh.write(f"{float(a):.9g},{float(b):.9g}\n")
        with open(OUT / f"{name}_expected.tsv", "w") as fh:
            fh.write("n\tk\tp\tratio\tartifact\tlevel\n")
            for n, r in rows:
                fh.write(f"{n}\t{r['k']!r}\t{r['p']!r}\t{r['ratio']!r}\t{int(r['artifact'])}\t{r['level']}\n")
        lv = [r["level"] for _, r in rows]; kp = [r["level_kp"] for _, r in rows]
        sh = lambda v: " ".join(f"{k} {100 * v.count(k) / len(v):.1f}%" for k in ("GOOD", "FAIR", "POOR"))
        lines.append(f"{name}: {t0}-{t1} s, {len(d)} samples, {len(rows)} verdicts; kurtosis and band share alone: {sh(kp)}; "
                     f"with the artifact check: {sh(lv)}; artifact at {sum(r['artifact'] for _, r in rows)} verdicts")
    text = "\n".join(lines) + "\n"; print(text, end="")
    (HERE / "analysis" / "sqi_fixtures.txt").write_text(text)


if __name__ == "__main__":
    main()
