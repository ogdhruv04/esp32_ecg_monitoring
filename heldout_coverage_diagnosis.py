#!/usr/bin/env python3
# Usage: python3 -I heldout_coverage_diagnosis.py <mitdb dir> <record> [...]  > analysis/heldout_coverage_diagnosis.txt
# Diagnostic only: WHY tp2 flags beats on held-out records with collapsed coverage.
# Uses the frozen detector unchanged; wraps two methods to record each beat's flag reason.
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, wfdb
from scipy import signal as sps
import pan_tompkins as P
H = sys.argv[1]; FS = 256.0
def filt(x, causal):
    f2 = sps.sosfilt if causal else sps.sosfiltfilt; f1 = sps.lfilter if causal else sps.filtfilt
    y = f2(sps.butter(4, .5, "highpass", fs=FS, output="sos"), x)
    b, a = sps.iirnotch(60., 30., fs=FS); y = f1(b, a, y)
    return f2(sps.butter(4, 40., "lowpass", fs=FS, output="sos"), y)
print("# Held-out coverage diagnosis (diagnostic only; no parameter changed). Frozen tp2.1 detector.")
print("# Per beat: polarity sign from the rolling median beat (0 = undecided: lobes within 1.5x),")
print("# and the median beat's lobe ratio (larger/smaller) when 8+ beats are in.")
print(f"{'rec':>4} {'filter':>10} {'beats':>6} {'flagged':>8} {'undecided':>9} {'edge/gap':>8} {'corr':>5} | lobe ratio median, share < 1.5")
for rec in sys.argv[2:]:
    r = wfdb.rdrecord(f"{H}/{rec}"); names = list(r.sig_name)
    c = names.index("MLII") if "MLII" in names else 0
    x = sps.resample(r.p_signal[:, c], int(round(r.p_signal.shape[0] * FS / 360)))
    for causal in (False, True):
        d = P.PanTompkins(FS)
        signs, ratios = [], []
        orig = d._polarity
        def pol(orig=orig):
            s, t = orig()
            signs.append(s)
            if t is not None:
                ratios.append(max(max(t), -min(t)) / max(1e-12, min(max(t), -min(t))))
            return s, t
        d._polarity = pol
        for v in filt(x, causal): d.process(v)
        fl = sum(b["flagged"] for b in d.beats); und = sum(1 for s in signs if s == 0)
        other = fl - und - d.corr_flagged
        rt = np.array(ratios)
        print(f"{rec:>4} {'causal' if causal else 'zero-phase':>10} {len(d.beats):6d} {fl:8d} {und:9d} {other:8d} {d.corr_flagged:5d} | "
              f"{np.median(rt):.2f}, {100*np.mean(rt < 1.5):.0f}%")
