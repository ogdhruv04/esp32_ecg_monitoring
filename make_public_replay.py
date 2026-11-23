#!/usr/bin/env python3
"""Convert a public ECG record into a capture CSV for the app's replay mode.

    ./make_public_replay.py --dir <main checkout>/data/mitdb --record 103 --seconds 360

Our own captures are all too short or too poor for every Session measure to
pass its minimum window (analysis/app_session_reference.txt), so the report's
fully populated layout can only be seen on public data. This writes
android_app/replay_public/mitdb<record>.csv, which debug builds bundle when it
exists (app/build.gradle.kts). The directory is gitignored: datasets are never
committed (docs/datasets.md). MIT-BIH is ODC-By 1.0; cite it and PhysioNet
wherever an image made from it is shown.

Only DEVELOPMENT records are accepted (docs/datasets.md): the held-out 36 are
spent and are not used for anything, display included.

Conversion: MLII, resampled to 256 Hz (algorithms.frontend.resample), scaled
from mV to codes by the nominal MAX30003 factor (2621.44 codes per mV at gain
20, docs/MAX30003_datasheet_check.md #23), so the ECG paper shows the record's
real millivolts. ETAG 0, leadoff 0, isr_micros synthesised from the index.
MIT-BIH mains is 60 Hz and the app notches 50 Hz; record 103 has little mains.
"""
import argparse, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from algorithms import frontend

DEV = {"100", "101", "103", "105", "106", "108", "109", "119", "203", "208", "222", "228"}
CODES_PER_MV = 2621.44

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--record", default="103")
ap.add_argument("--seconds", type=float, default=360.0)
args = ap.parse_args()
if args.record not in DEV:
    sys.exit(f"refusing: {args.record} is not one of the 12 development records")

import wfdb
r = wfdb.rdrecord(f"{args.dir}/{args.record}", sampto=int(args.seconds * 360))
names = [n.strip() for n in r.sig_name]
x = r.p_signal[:, names.index("MLII")]
y = frontend.resample(x, float(r.fs), 256.0)
codes = np.round(y * CODES_PER_MV).astype(int)
out = pathlib.Path("android_app/replay_public"); out.mkdir(parents=True, exist_ok=True)
path = out / f"mitdb{args.record}.csv"
with open(path, "w") as f:
    f.write("index,isr_micros,value,etag,leadoff\n")
    for i, c in enumerate(codes):
        f.write(f"{i},{int(i * 1e6 / 256)},{c},0,0\n")
print(f"wrote {path}: {len(codes)} samples ({len(codes) / 256:.0f} s), MIT-BIH {args.record} MLII")
