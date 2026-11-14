#!/usr/bin/env python3
"""Replay the app's quality gate (signal_quality.py = SignalQuality.kt) on our recordings.

    ./sqi_replay.py --captures <main>/captures      # -> analysis/sqi_replay_app_gate_sqi2.txt

Each capture goes through the app's chain as Python can reproduce it: causal
monitoring filter (scipy's Butterworth sections, an approximation of
EcgFilter.kt), the 0.6 s running-median baseline remover, the detector's
5-15 Hz signal, 5 s buffers, one verdict every 64 samples from the first
second on. Lost samples close up, as in the app's buffers.

"before" is the gate up to 13 Nov 2026: kurtosis and band share alone.
"now" adds the artifact check (sqi2). Both come from the same verdicts.

The earlier report, analysis/sqi_replay_app_gate_dual01-03.txt, came from the
first version of this script: it skipped the first 10 s, stepped 1 s, used a
centred median and a Butterworth 5-15 Hz band. Its shares are therefore not
the "before" column here. The app's own numbers are in
analysis/app_quality_gate_replay.txt (QualityGateReplayTest, through EcgPipeline).
"""
import argparse, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import signal_quality as SQ
from algorithms import frontend

ap = argparse.ArgumentParser()
ap.add_argument("--captures", default="captures")
args = ap.parse_args()
HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
FILES = [("tb02", "20261027_174352_testboard02.csv"), ("tb01", "20261027_173714_testboard01.csv"),
         ("dual03 chest", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv"),
         ("dual03 finger", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv"),
         ("dual01 chest (failed)", "20260929_153252_dual01_c3chest_wroomfinger_ring.csv"),
         ("dual01 finger (failed)", "20260929_153252_dual01_c3chest_wroomfinger_ref.csv"),
         ("dual02 chest (failed)", "20260929_155511_dual02_rbias_c3chest_wroomfinger_ring.csv"),
         ("dual02 finger", "20260929_155511_dual02_rbias_c3chest_wroomfinger_ref.csv")]


def shares(v):
    return "  ".join(f"{k} {100 * np.mean(np.array(v) == k):5.1f}%" for k in ("GOOD", "FAIR", "POOR"))


def main():
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out = [f"# ./sqi_replay.py   commit {commit}; gate {SQ.VERSION}; settings {SQ.CONFIG['artifact']['memory_blocks']} blocks, "
           f"ratio {SQ.CONFIG['artifact']['ratio_max']:g}, hold {SQ.CONFIG['artifact']['hold_blocks']}",
           "# Python replay of the app's chain, whole recording, one verdict every 64 samples. before = kurtosis and band share alone.",
           "# No quality reference exists for these recordings; tb02's first 42 s are known electrode-settling transients.", ""]
    for name, fn in FILES:
        val, skips, _ = frontend.load_capture(f"{args.captures}/{fn}")
        at, res = SQ.replay(frontend.filter_ecg(val, FS, 50.0, causal=True, harmonic=True), FS)
        t = at / FS
        parts = [("first 42 s", t <= 42), ("after 45 s", t > 45)] if name == "tb02" else [("", np.ones(len(t), bool))]
        for label, m in parts:
            r = [q for q, k in zip(res, m) if k]
            before = [q["level_kp"] for q in r]; now = [q["level"] for q in r]
            lost = sum(1 for a, b in zip(before, now) if a == "GOOD" and b != "GOOD")
            out.append(f"{(name + (', ' + label if label else '')):24} {len(r):5d} verdicts | before: {shares(before)} | now: {shares(now)} | "
                       f"artifact at {sum(q['artifact'] for q in r)}; GOOD turned to POOR {lost} | "
                       f"kSQI median {np.median([q['k'] for q in r]):5.1f}  pSQI median {np.median([q['p'] for q in r]):.3f}")
    text = "\n".join(out) + "\n"; print(text, end="")
    (HERE / "analysis" / "sqi_replay_app_gate_sqi2.txt").write_text(text)


if __name__ == "__main__":
    main()
