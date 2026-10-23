#!/usr/bin/env python3
"""Integrity of capture CSVs, judged on the host (CLAUDE.md rule): index
continuity, duplicates, malformed rows. Saves analysis/integrity_<stem>.txt.

    ./integrity.py captures/<stamp>_<label>_ring.csv captures/<stamp>_<label>_ref.csv
"""
import pathlib, sys, io, contextlib
import numpy as np

def check(path):
    lines = pathlib.Path(path).read_text().splitlines()
    head, rows = lines[0].split(","), lines[1:]
    ok = [r.split(",") for r in rows if len(r.split(",")) == len(head)]
    malformed = len(rows) - len(ok)
    col = {h: i for i, h in enumerate(head)}
    idx = np.array([int(r[col["index"]]) for r in ok], dtype=np.int64)
    d = np.diff(idx)
    missing = int(np.sum(d[d > 1] - 1))
    print(f"{pathlib.Path(path).name}")
    print(f"  rows {len(rows)}  malformed {malformed}  index {idx[0]}..{idx[-1]} "
          f"(span {idx[-1]-idx[0]+1})")
    print(f"  missing {missing}  gaps {int(np.sum(d > 1))}  duplicates {int(np.sum(d == 0))}  "
          f"backward jumps {int(np.sum(d < 0))}")
    if "host_time" in col:
        t = np.array([float(r[col["host_time"]]) for r in ok])
        print(f"  {len(ok)} samples over {t[-1]-t[0]:.2f} s host time = {(len(ok)-1)/(t[-1]-t[0]):.2f} SPS")

paths = sys.argv[1:]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for p in paths:
        check(p)
print(buf.getvalue(), end="")
stem = pathlib.Path(paths[0]).stem.rsplit("_", 1)[0]
out = pathlib.Path("analysis") / f"integrity_{stem}.txt"
out.write_text(f"# ./integrity.py {' '.join(paths)}\n" + buf.getvalue())
print(f"saved {out}")
