#!/usr/bin/env python3
"""Development of the quality gate's artifact check (sqi2).

    ./develop_sqi_artifact.py --captures <main>/captures --mitdb <main>/data/mitdb <main>/data/mitdb_heldout \
                              --nst <main>/data/nstdb [--jobs 3]

The gate (signal_quality.py, SignalQuality.kt) called electrode-settling
transients GOOD, because kurtosis rewards spikes. The check added in sqi2
compares the swing (max - min) of each 1 s block of the display signal with
the swing of an ordinary second: a percentile of the last M block swings. A
block more than A times that is an artifact, and the verdict is POOR for
`hold` blocks from it.

This script scores a grid of (M, percentile, A, hold) on every block the OLD
gate called GOOD, 5 s window ending at the block's end:

  should be rejected   tb02's first 42 s (settling transients; the beats are
                       clean from 44 s on, analysis/app_live_hr.txt)
  should NOT be        tb02 after 45 s, dual03, all 48 MIT-BIH Arrhythmia
                       records (arrhythmia, ectopic beats, pauses), the clean
                       segments of the MIT-BIH Noise Stress Test records
  for information      tb01 (a burst of large swings at 81-96 s), dual01 and dual02 (failed
                       recordings), the noisy NST segments by SNR

ALL OF IT IS DEVELOPMENT DATA. "Should be rejected" rests on one episode in
one recording. Nothing here is a held-out result.

Public data: MLII (first signal of the NST records), 360 -> 256 Hz, monitoring
filter with a 60 Hz notch; ours 50 and 100 Hz. Causal, as on the phone. NST
noise starts at 5 min and alternates 2 min on, 2 min off; the 5 s after each
change are left out of both groups.

Saves analysis/sqi_artifact_dev.txt.
"""
import argparse, contextlib, glob, io, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--captures", required=True)
ap.add_argument("--mitdb", nargs="+", required=True)
ap.add_argument("--nst", required=True)
ap.add_argument("--jobs", type=int, default=3)
args = ap.parse_args()

import signal_quality as SQ
from algorithms import frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
BLOCK = int(SQ.CONFIG["artifact"]["block_s"] * FS)
WIN = int(SQ.CONFIG["window_s"] * FS)
OWN = [("tb02", "20261027_174352_testboard02.csv"), ("tb01", "20261027_173714_testboard01.csv"),
       ("dual03 chest", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv"),
       ("dual03 finger", "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv"),
       ("dual01 chest", "20260929_153252_dual01_c3chest_wroomfinger_ring.csv"),
       ("dual01 finger", "20260929_153252_dual01_c3chest_wroomfinger_ref.csv"),
       ("dual02 chest", "20260929_155511_dual02_rbias_c3chest_wroomfinger_ring.csv"),
       ("dual02 finger", "20260929_155511_dual02_rbias_c3chest_wroomfinger_ref.csv")]
GRID = [(m, q, a, h) for m in (30, 60) for q in (25, 50) for a in (3.0, 4.0, 5.0, 6.0) for h in (5, 10, 15)]


def blocks(filtered):
    """Per 1 s block: its swing, and the old gate's verdict on the 5 s window
    ending with it (0 GOOD, 1 FAIR, 2 POOR, 3 before 5 s have arrived)."""
    d = SQ.display_signal(filtered, FS).astype(float); q = SQ.qrs_signal(filtered, FS).astype(float)
    nb = len(d) // BLOCK
    sw = np.array([d[i * BLOCK:(i + 1) * BLOCK].max() - d[i * BLOCK:(i + 1) * BLOCK].min() for i in range(nb)], dtype=np.float32)
    lv = np.full(nb, 3, dtype=np.int8)
    gate = SQ.SignalQuality(FS)
    for j in range(nb):
        e = (j + 1) * BLOCK
        if e >= WIN:
            r = gate.assess(d[e - WIN:e], q[e - WIN:e])
            lv[j] = ("GOOD", "FAIR", "POOR").index(r["level_kp"])
    return sw, lv


def one(job):
    kind, name, path = job
    if kind == "own":
        val, _, _ = frontend.load_capture(path)
        return name, blocks(frontend.filter_ecg(val, FS, 50.0, causal=True, harmonic=True))
    import wfdb
    r = wfdb.rdrecord(path); names = list(r.sig_name)
    x = frontend.resample(r.p_signal[:, names.index("MLII") if "MLII" in names else 0], float(r.fs))
    return name, blocks(frontend.filter_ecg(x, FS, 60.0, causal=True))


def rejected(sw, m, q, a, hold):
    """Per block: is the verdict forced to POOR? (the rule of signal_quality.py,
    which is the q = 50 case; at block ends the phone's rule is exactly this)."""
    n = len(sw); flag = np.zeros(n, bool)
    for j in range(n):
        h = np.sort(sw[max(0, j - m + 1):j + 1])
        flag[j] = sw[j] > a * h[int((len(h) - 1) * q / 100)]
    return np.array([flag[max(0, j - hold + 1):j + 1].any() for j in range(n)])


def main():
    jobs = [("own", "own:" + n, f"{args.captures}/{f}") for n, f in OWN]
    for d in args.mitdb:
        jobs += [("pub", "mit:" + os.path.basename(p)[:-4], p[:-4]) for p in sorted(glob.glob(f"{d}/*.hea"))]
    jobs += [("pub", "nst:" + os.path.basename(p)[:-4], p[:-4]) for p in sorted(glob.glob(f"{args.nst}/11*.hea"))]
    import multiprocessing as mp
    with mp.Pool(args.jobs, maxtasksperchild=4) as pool:
        data = dict(pool.imap_unordered(one, jobs, chunksize=1))
    mit = sorted(k for k in data if k.startswith("mit:")); nst = sorted(k for k in data if k.startswith("nst:"))
    noisy = lambda t: (t > 305) & (((t - 300) // 120) % 2 == 0) & (((t - 300) % 120) >= 5)
    clean = lambda t: (t <= 300) | ((((t - 300) // 120) % 2 == 1) & (((t - 300) % 120) >= 5))
    groups = [("tb02 <=42s", ["own:tb02"], lambda t: t <= 42), ("tb02 >45s", ["own:tb02"], lambda t: t > 45),
              ("dual03", ["own:dual03 chest", "own:dual03 finger"], None), ("MIT-BIH", mit, None), ("NST clean", nst, clean),
              ("tb01", ["own:tb01"], None), ("dual01+02", [k for k in data if k.startswith("own:dual01") or k.startswith("own:dual02")], None),
              ("NST noisy", nst, noisy)]

    def share(keys, sel, cfg):
        num = den = 0
        for k in keys:
            sw, lv = data[k]; t = np.arange(len(sw)) + 1.0
            m = lv == 0
            if sel:
                m &= sel(t)
            num += int((rejected(sw, *cfg) & m).sum()); den += int(m.sum())
        return num, den

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "signal_quality.py", "sqi_config.json",
                                "develop_sqi_artifact.py"], capture_output=True, text=True).stdout.strip()
        print(f"# ./develop_sqi_artifact.py   commit {commit}{' + uncommitted changes' if dirty else ''}; gate {SQ.VERSION}")
        print(f"# {len(OWN)} own recordings, {len(mit)} MIT-BIH Arrhythmia records, {len(nst)} MIT-BIH Noise Stress Test records. All development data.")
        print("# A block = 1 s of the display signal. Only blocks the old gate (kurtosis and band share) called GOOD are counted.\n")
        print("old gate, share of blocks by verdict (5 s window ending at each block):")
        for name, keys, sel in groups:
            lv = np.concatenate([data[k][1][(sel(np.arange(len(data[k][0])) + 1.0) if sel else slice(None))] for k in keys])
            lv = lv[lv < 3]
            print(f"  {name:11} {len(lv):6d} blocks: GOOD {100 * np.mean(lv == 0):5.1f}%  FAIR {100 * np.mean(lv == 1):5.1f}%  POOR {100 * np.mean(lv == 2):5.1f}%")
        for s in ("24", "18", "12", "06", "00", "_6"):
            keys = [k for k in nst if k.endswith(s)]
            lv = np.concatenate([data[k][1][noisy(np.arange(len(data[k][0])) + 1.0)] for k in keys])
            print(f"  NST noisy, SNR {s.replace('_', '-'):>3} dB {len(lv):5d} blocks: GOOD {100 * np.mean(lv == 0):5.1f}%  FAIR {100 * np.mean(lv == 1):5.1f}%  POOR {100 * np.mean(lv == 2):5.1f}%")

        print("\n=== grid: share of old-GOOD blocks the check turns to POOR (blocks in brackets on the first row) ===")
        print("memory M blocks, reference = that percentile of their swings, artifact = swing > A x reference, POOR for `hold` blocks")
        dens = [share(keys, sel, GRID[0])[1] for _, keys, sel in groups]
        print(f"{'M':>3} {'pct':>3} {'A':>3} {'hold':>4} | " + " ".join(f"{g[0]:>11}" for g in groups))
        print(f"{'':16} | " + " ".join(f"{'(' + str(d) + ')':>11}" for d in dens))
        cur = SQ.CONFIG["artifact"]; chosen = (cur["memory_blocks"], 50, cur["ratio_max"], cur["hold_blocks"])
        for cfg in GRID:
            row = [share(keys, sel, cfg) for _, keys, sel in groups]
            mark = "  <- sqi_config.json" if cfg == chosen else ""
            print(f"{cfg[0]:3d} {cfg[1]:3d} {cfg[2]:3.0f} {cfg[3]:4d} | " + " ".join(f"{100 * a / b:10.2f}%" if b else f"{'-':>11}" for a, b in row) + mark)

        print(f"\n=== the setting in sqi_config.json: memory {chosen[0]}, median, A {chosen[2]:g}, hold {chosen[3]} ===")
        for name, keys, sel in groups:
            a, b = share(keys, sel, chosen)
            print(f"  {name:11} {a:5d} of {b:6d} old-GOOD blocks turned to POOR ({100 * a / b:.2f}%)" if b else f"  {name:11} no old-GOOD blocks")
        for s in ("24", "18", "12", "06", "00", "_6"):
            a, b = share([k for k in nst if k.endswith(s)], noisy, chosen)
            print(f"  NST noisy, SNR {s.replace('_', '-'):>3} dB: {a} of {b} old-GOOD blocks turned to POOR")
        hit = [(k, *share([k], None, chosen)) for k in mit]
        print("  MIT-BIH records with any old-GOOD block turned to POOR: " + (", ".join(f"{k[4:]} ({a} of {b})" for k, a, b in hit if a) or "none"))
        for k in ("own:tb02", "own:tb01"):
            sw, lv = data[k]; rej = rejected(sw, *chosen)
            ref = [float(np.sort(sw[max(0, j - chosen[0] + 1):j + 1])[(min(j + 1, chosen[0]) - 1) // 2]) for j in range(len(sw))]
            lim = 50 if k == "own:tb02" else len(sw)
            print(f"\n  {k[4:]}, per second: swing/reference, old verdict (G F P, w = before 5 s), x = turned to POOR"
                  + (" (first 50 s)" if k == "own:tb02" else " (seconds with x or a swing over twice the reference)"))
            cells = [f"{j + 1}:{sw[j]:.0f}/{ref[j]:.0f}{'GFPw'[lv[j]]}{'x' if rej[j] else ''}" for j in range(lim)
                     if k == "own:tb02" or rej[j] or sw[j] > 2 * ref[j]]
            for i in range(0, len(cells), 10):
                print("    " + "  ".join(cells[i:i + 10]))
        # the streaming class must agree with the block rule at block ends
        worst = 0
        for k in [k for k in data if k.startswith("own:")]:
            sw, _ = data[k]; g = SQ.SignalQuality(FS); got = []
            for s in sw:
                for v in [0.0] * (BLOCK - 2) + [0.0, float(s)]:      # a block whose swing is s
                    g.track(v)
                got.append(g.artifact_state()[0])
            worst += int(np.sum(np.array(got) != rejected(sw.astype(float), *chosen)))
        print(f"\nsignal_quality.SignalQuality fed blocks with these swings disagrees with the block rule above on {worst} blocks of the own recordings.")
    text = buf.getvalue(); print(text, end="")
    (HERE / "analysis" / "sqi_artifact_dev.txt").write_text(text); print(f"saved {HERE / 'analysis' / 'sqi_artifact_dev.txt'}")


if __name__ == "__main__":
    main()
