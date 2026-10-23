#!/usr/bin/env python3
"""Which point in the QRS to time a beat from, and whether sub-sample
interpolation helps. Item 1 of the algorithm plan: HRV is built from beat
times, so their jitter sets how far any HRV figure can be trusted.

    ./fiducial.py dual  captures/<..>_ring.csv captures/<..>_ref.csv --chest ring   # ring CSV first
    ./fiducial.py mitdb [--dir data/mitdb]

Four fiducials, each located around the beats pan_tompkins.detect() finds
(the detector itself is not changed):

  bp        index of max |5-15 Hz bandpassed| - what pan_tompkins reports today
  bp+parab  the same, with parabolic sub-sample interpolation
  R         peak of the dominant QRS deflection in the filtered ECG, after
            correcting each channel's polarity from its median beat
  R+parab   the same, with parabolic sub-sample interpolation

Every fiducial is computed under the zero-phase filter (offline analysis) and
the causal one (what the phone runs).

PRIMARY validation - dual: finger and chest record the same heartbeats, so the
same fiducial on both should give the same RR intervals. All fiducials are
scored on one fixed set of matched beat pairs, so they are compared like for
like. The finger-minus-chest beat-time spread is the two channels' combined
jitter (plus any real beat-to-beat change in propagation, which is not
separable here).

SECONDARY - mitdb: annotation times are a reference with their own jitter, not
ground truth. With three timings per beat (annotation, fiducial on lead 0,
fiducial on lead 1), a three-cornered hat estimates each one's own jitter,
assuming the three errors are independent.

Saves analysis/fiducial_<name>.txt (and a .png for dual).
"""
import argparse, io, contextlib, pathlib, sys
import numpy as np
from scipy import signal as sps
import pan_tompkins

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["dual", "mitdb"])
ap.add_argument("files", nargs="*")
ap.add_argument("--chest", choices=["ring", "ref"], default="ring",
                help="which of the two dual CSVs is the chest electrode")
ap.add_argument("--dir", default="data/mitdb")
ap.add_argument("--fs", type=float, default=256.0)
ap.add_argument("--skip-s", type=float, default=10.0)
args = ap.parse_args()
FS = args.fs
FIDS = ["bp", "bp+parab", "R", "R+parab"]
FILTERS = ["zero-phase", "causal"]

# ------------------------------------------------------------------ filters
def filt(x, fs, mains, harmonic, causal):
    """0.5 Hz HP, mains notch (+2nd harmonic if requested), 40 Hz LP.
    harmonic=True matches agreement.py; False matches benchmark_mitdb.py."""
    f2 = (sps.sosfilt if causal else sps.sosfiltfilt)
    f1 = (sps.lfilter if causal else sps.filtfilt)
    y = f2(sps.butter(4, 0.5, "highpass", fs=fs, output="sos"), x)
    notches = [mains] + ([2 * mains] if harmonic and 2 * mains < fs / 2 else [])
    for f in notches:
        b, a = sps.iirnotch(f, 30.0, fs=fs); y = f1(b, a, y)
    return f2(sps.butter(4, 40.0, "lowpass", fs=fs, output="sos"), y)

def bandpassed(y, fs):
    """The detector's own 5-15 Hz stage (pan_tompkins._rbj biquads), causal."""
    out = y
    for kind, f0 in (("hp", 5.0), ("lp", 15.0)):
        q = pan_tompkins._rbj(kind, f0, 0.7071, fs)
        out = sps.lfilter(q.b, (1.0,) + q.a, out)
    return out

# ---------------------------------------------------------------- fiducials
def parabolic(v, k):
    """Vertex offset of the parabola through v[k-1..k+1], in samples (|d|<=0.5).
    0 when k is on an edge or is not a strict local maximum."""
    if k <= 0 or k >= len(v) - 1:
        return 0.0
    a, b, c = v[k - 1], v[k], v[k + 1]
    den = a - 2 * b + c
    if not (den < 0 and b >= a and b >= c):
        return 0.0
    return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))

def polarity(y, det, fs):
    """+1 or -1: sign of the dominant deflection of the median beat."""
    w = int(0.10 * fs)
    segs = [y[d - w:d + w] for d in det if d - w >= 0 and d + w < len(y)]
    m = np.median(np.array(segs), axis=0)
    return 1.0 if m[np.argmax(np.abs(m))] > 0 else -1.0

def fiducials(y, det, fs, sign=None):
    """Times in samples (float) for each fiducial, one per detection; NaN if
    the R search window runs off the signal."""
    bp = np.abs(bandpassed(y, fs))
    s = polarity(y, det, fs) if sign is None else sign
    ys = s * y
    lo, hi = int(0.100 * fs), int(0.060 * fs)       # R search: 100 ms before .. 60 ms after
    out = {k: np.full(len(det), np.nan) for k in FIDS}
    for i, d in enumerate(det):
        out["bp"][i] = d
        out["bp+parab"][i] = d + parabolic(bp, d)
        if d - lo < 1 or d + hi >= len(y) - 1:
            continue
        k = d - lo + int(np.argmax(ys[d - lo:d + hi + 1]))
        out["R"][i] = k
        out["R+parab"][i] = k + parabolic(ys, k)
    return out, s

# --------------------------------------------------------------------- stats
def rsd(x):
    """Robust sd: 1.4826 x median absolute deviation."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")

def rmssd_ms(rr_ms):
    """Phone rules (BeatDetector.rmssdMs): intervals 300-2000 ms; successive
    differences only between two valid adjacent intervals, and <= 300 ms."""
    v = lambda m: np.isfinite(m) and 300.0 <= m <= 2000.0
    d = [rr_ms[i] - rr_ms[i - 1] for i in range(1, len(rr_ms))
         if v(rr_ms[i]) and v(rr_ms[i - 1]) and abs(rr_ms[i] - rr_ms[i - 1]) <= 300.0]
    return float(np.sqrt(np.mean(np.square(d)))) if d else float("nan"), len(d)

def greedy(ref_t, test_t, tol):
    """One-to-one nearest matching within tol (same rule as EC57 / agreement.py).
    Returns (ref_index, test_index) pairs."""
    used = np.zeros(len(ref_t), bool); pairs = []
    for j, t in enumerate(test_t):
        i = np.searchsorted(ref_t, t)
        best, bd = -1, tol + 1
        for k in (i - 1, i, i + 1):
            if 0 <= k < len(ref_t) and not used[k] and abs(ref_t[k] - t) < bd:
                best, bd = k, abs(ref_t[k] - t)
        if best >= 0 and bd <= tol:
            used[best] = True; pairs.append((best, j))
    return pairs

# ======================================================================= dual
def load_dual(path):
    raw = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                        invalid_raise=False)
    idx = raw["index"].astype(np.int64); val = raw["value"].astype(float)
    host = raw["host_time"].astype(float)
    s = int(args.skip_s * FS)
    idx, val, host = idx[s:], val[s:], host[s:]
    br = np.flatnonzero(np.diff(idx) != 1) + 1
    keep = max(np.split(np.arange(len(idx)), br), key=len)
    return val[keep], float(host[keep][0])

def run_dual():
    a, b = args.files
    chest_p, finger_p = (a, b) if args.chest == "ring" else (b, a)
    (cx, ch0), (fx, fh0) = load_dual(chest_p), load_dual(finger_p)
    print(f"chest  {chest_p}\nfinger {finger_p}")
    print(f"skip {args.skip_s:g} s; chest {len(cx)/FS:.1f} s, finger {len(fx)/FS:.1f} s clean\n")
    res = {}
    for fname in FILTERS:
        causal = fname == "causal"
        ch = {}
        for site, x, h0 in (("chest", cx, ch0), ("finger", fx, fh0)):
            y = filt(x, FS, 50.0, True, causal)
            det = pan_tompkins.detect(y, FS)
            fid, sign = fiducials(y, det, FS)
            ch[site] = dict(h0=h0, det=det, fid=fid, sign=sign)
        # Fix the beat pairs once, from the detector's own beat times, so every
        # fiducial is scored on exactly the same beats.
        tc = ch["chest"]["h0"] + ch["chest"]["det"] / FS
        tf = ch["finger"]["h0"] + ch["finger"]["det"] / FS
        off = 0.0
        for _ in range(4):                      # host clocks align to tens of ms
            j = np.clip(np.searchsorted(tc, tf - off), 1, len(tc) - 1)
            near = np.where(np.abs(tc[j] - (tf - off)) < np.abs(tc[j - 1] - (tf - off)), j, j - 1)
            dd = (tf - off) - tc[near]
            off += float(np.median(dd[np.abs(dd) < 0.15]))
        pairs = greedy(tc, tf - off, 0.15)
        ok = [(ic, jf) for ic, jf in pairs
              if all(np.isfinite(ch["chest"]["fid"][k][ic]) and np.isfinite(ch["finger"]["fid"][k][jf])
                     for k in FIDS)]
        res[fname] = dict(ch=ch, pairs=ok, off=off, n_det=(len(tc), len(tf)))
    return res

def report_dual(res):
    for fname in FILTERS:
        r = res[fname]; ch = r["ch"]; pairs = r["pairs"]
        print(f"=== {fname} filter ===")
        print(f"beats detected chest {r['n_det'][0]}, finger {r['n_det'][1]}; matched pairs {len(pairs)}; "
              f"polarity chest {ch['chest']['sign']:+.0f}, finger {ch['finger']['sign']:+.0f}")
        ic = np.array([p[0] for p in pairs]); jf = np.array([p[1] for p in pairs])
        # consecutive pairs: chest i,i+1 matched to finger j,j+1
        cons = np.flatnonzero((np.diff(ic) == 1) & (np.diff(jf) == 1))
        print("beat dt = finger - chest beat time, median removed. 'sd' is every pair; 'jitter' excludes")
        print("pairs off by >20 ms (gross mislocations, counted separately). Robust sd is not")
        print("meaningful for integer fiducials, which move in 3.9 ms steps.")
        print(f"{'fiducial':10} {'beat dt sd':>10} {'jitter':>7} {'>20ms':>6} | "
              f"{'RR diff sd':>10} {'LoA':>15} | {'RMSSD ch':>8} {'fing':>6} {'diff':>6} {'n':>4} | "
              f"{'all-beats RMSSD ch':>18} {'fing':>6}")
        r["rows"] = {}
        for k in FIDS:
            t_c = ch["chest"]["fid"][k] / FS * 1000; t_f = ch["finger"]["fid"][k] / FS * 1000
            dt = t_f[jf] - t_c[ic]; dt = dt - np.median(dt)
            rr_c = t_c[ic[cons + 1]] - t_c[ic[cons]]
            rr_f = t_f[jf[cons + 1]] - t_f[jf[cons]]
            drr = rr_f - rr_c; bias, sd = float(np.mean(drr)), float(np.std(drr, ddof=1))
            # like-for-like RMSSD: successive differences only where both
            # channels have two valid adjacent intervals, same beats on both
            valid = lambda m: 300.0 <= m <= 2000.0
            sd_c, sd_f = [], []
            for q in range(1, len(cons)):
                if cons[q] != cons[q - 1] + 1:
                    continue                       # not adjacent intervals
                a1, a2, b1, b2 = rr_c[q - 1], rr_c[q], rr_f[q - 1], rr_f[q]
                if not all(valid(v) for v in (a1, a2, b1, b2)):
                    continue
                if abs(a2 - a1) > 300 or abs(b2 - b1) > 300:
                    continue
                sd_c.append(a2 - a1); sd_f.append(b2 - b1)
            rm_c = float(np.sqrt(np.mean(np.square(sd_c)))); rm_f = float(np.sqrt(np.mean(np.square(sd_f))))
            # all detected beats per channel, independently (as the phone would)
            ac, _ = rmssd_ms(np.diff(t_c)); af, _ = rmssd_ms(np.diff(t_f))
            r["rows"][k] = dict(dt=dt, drr=drr)
            big = np.abs(dt) > 20
            r["rows"][k]["out"] = [(float(ch["chest"]["fid"][k][ic[q]] / FS), float(dt[q]))
                                   for q in np.flatnonzero(big)]
            print(f"{k:10} {np.std(dt, ddof=1):8.2f}ms {np.std(dt[~big], ddof=1):5.2f}ms {int(big.sum()):6d} | "
                  f"{sd:8.2f}ms {bias-1.96*sd:+7.1f}..{bias+1.96*sd:+5.1f} | "
                  f"{rm_c:6.1f}ms {rm_f:6.1f} {rm_f-rm_c:+6.1f} {len(sd_c):4d} | "
                  f"{ac:16.1f}ms {af:6.1f}")
        for k in FIDS:
            o = r["rows"][k]["out"]
            if 0 < len(o) <= 6:
                print(f"  {k} gross: " + ", ".join(f"{dtv:+.0f} ms at {t:.1f} s" for t, dtv in o))
            elif o:
                print(f"  {k} gross: {len(o)} pairs, dt {min(v for _, v in o):+.0f}..{max(v for _, v in o):+.0f} ms")
        print()

def plot_dual(res, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.2), sharex=True)
    bins = np.arange(-40, 41, 1.0)
    for row, fname in enumerate(FILTERS):
        for col, k in enumerate(FIDS):
            ax = axes[row, col]; dt = res[fname]["rows"][k]["dt"]
            ax.hist(np.clip(dt, -40, 40), bins=bins, color="#2a78d6" if "R" in k else "#eb6834")
            ax.set_title(f"{fname} | {k}\nsd {np.std(dt, ddof=1):.1f} ms, robust {rsd(dt):.1f} ms", fontsize=10)
            ax.axvline(0, color="0.6", lw=.8)
            if row == 1: ax.set_xlabel("finger - chest, ms")
    fig.suptitle("Finger minus chest beat time on the same beats (median removed, clipped at +-40 ms)", fontsize=12)
    fig.tight_layout(); fig.savefig(png, dpi=110)

# ====================================================================== mitdb
def run_mitdb():
    import wfdb
    BEAT = set("NLRejAaJSVEFP/fQ")
    AAMI_N = set("NLRej")      # AAMI class N: normally conducted beats, incl. bundle branch block
    recs = sorted(p.stem for p in pathlib.Path(args.dir).glob("*.hea"))
    print(f"MIT-BIH, {len(recs)} records in {args.dir}: {' '.join(recs)}")
    print("Front end as benchmark_mitdb.py: resampled to 256 Hz, 0.5-40 Hz, single 60 Hz notch.")
    print("Annotation times kept unrounded (s), not snapped to the 256 Hz grid.")
    print("Only AAMI class-N beats (N L R e j) whose neighbouring beats are also class N are used;")
    print("detections matched to")
    print("annotations within 150 ms. Three-cornered hat on robust variances (1.4826 x MAD)^2,")
    print("per record, then the median across records. 'neg' = the estimate came out negative,")
    print("which happens when the independence assumption fails.\n")
    pooled = {f: {k: [] for k in FIDS} for f in FILTERS}
    hat = {f: {k: {"A": [], "L0": [], "L1": []} for k in FIDS} for f in FILTERS}
    rms = {f: {k: [] for k in FIDS} for f in FILTERS}
    rms_ann = []
    print("robust sd(lead-0 fiducial - annotation), ms. This mixes our jitter with the annotation's.")
    print(f"{'rec':>4} | {'':13} | zero-phase " + " ".join(f"{k:>8}" for k in FIDS)
          + " | causal " + " ".join(f"{k:>8}" for k in FIDS))
    for rec in recs:
        r = wfdb.rdrecord(f"{args.dir}/{rec}"); ann = wfdb.rdann(f"{args.dir}/{rec}", "atr")
        fs0 = float(r.fs)
        n_new = int(round(r.p_signal.shape[0] * FS / fs0))
        x0 = sps.resample(r.p_signal[:, 0].astype(float), n_new)
        x1 = sps.resample(r.p_signal[:, 1].astype(float), n_new)
        sym = np.array(ann.symbol); samp = np.array(ann.sample)
        isbeat = np.array([s in BEAT for s in sym])
        bidx = np.flatnonzero(isbeat)
        # class-N beats with class-N neighbours on both sides (so N-N intervals exist)
        nmask = np.zeros(len(sym), bool)
        for q in range(1, len(bidx) - 1):
            k = bidx[q]
            if sym[k] in AAMI_N and sym[bidx[q - 1]] in AAMI_N and sym[bidx[q + 1]] in AAMI_N:
                nmask[k] = True
        ann_t = samp[nmask] / fs0                   # seconds, unrounded
        cells = {f: [] for f in FILTERS}
        for fname in FILTERS:
            causal = fname == "causal"
            y0 = filt(x0, FS, 60.0, False, causal); y1 = filt(x1, FS, 60.0, False, causal)
            det = pan_tompkins.detect(y0, FS)
            f0, _ = fiducials(y0, det, FS); f1, _ = fiducials(y1, det, FS)
            pairs = greedy(ann_t, det / FS, 0.15)
            ia = np.array([p[0] for p in pairs], dtype=int); jd = np.array([p[1] for p in pairs], dtype=int)
            good = np.array([all(np.isfinite(f0[k][j]) and np.isfinite(f1[k][j]) for k in FIDS) for j in jd])
            ia, jd = ia[good.astype(bool)], jd[good.astype(bool)]
            if len(ia) < 30:
                cells[fname] = None
                continue
            A = ann_t[ia] * 1000
            for k in FIDS:
                L0 = f0[k][jd] / FS * 1000; L1 = f1[k][jd] / FS * 1000
                v = lambda u: rsd(u) ** 2
                vA0, vA1, v01 = v(L0 - A), v(L1 - A), v(L0 - L1)
                hat[fname][k]["A"].append((vA0 + vA1 - v01) / 2)
                hat[fname][k]["L0"].append((vA0 + v01 - vA1) / 2)
                hat[fname][k]["L1"].append((vA1 + v01 - vA0) / 2)
                pooled[fname][k].append(rsd(L0 - A))
                cells[fname].append(rsd(L0 - A))
                # RMSSD on runs of consecutive matched N beats: fiducial vs annotation
                cons = np.flatnonzero(np.diff(ia) == 1)
                rr_f = L0[cons + 1] - L0[cons]; rr_a = A[cons + 1] - A[cons]
                # break the series where consecutive intervals are not adjacent
                rf = []; ra = []
                for q in range(len(cons)):
                    if q > 0 and cons[q] != cons[q - 1] + 1:
                        rf.append(np.nan); ra.append(np.nan)
                    rf.append(rr_f[q]); ra.append(rr_a[q])
                mf, _ = rmssd_ms(rf); ma, _ = rmssd_ms(ra)
                rms[fname][k].append(mf - ma)
                if fname == "zero-phase" and k == "bp":
                    rms_ann.append(ma)
        if cells["zero-phase"] is None or cells["causal"] is None:
            print(f"{rec:>4} | skipped: fewer than 30 matched class-N beats"); continue
        print(f"{rec:>4} | {len(ia):5d} N beats | zero-phase " + " ".join(f"{v:8.2f}" for v in cells["zero-phase"])
              + " | causal " + " ".join(f"{v:8.2f}" for v in cells["causal"]))
    print()
    for fname in FILTERS:
        print(f"=== {fname}: three-cornered hat, own jitter sd (ms), median over records ===")
        print(f"{'fiducial':10} {'annotation':>11} {'lead 0':>8} {'lead 1':>8} | "
              f"{'RMSSD(fiducial) - RMSSD(annotation), ms: median':>48} {'[min, max]':>16}")
        for k in FIDS:
            def s(lst):
                m = float(np.median(lst)); return f"{np.sqrt(m):8.2f}" if m > 0 else "     neg"
            d = np.array(rms[fname][k])
            print(f"{k:10} {s(hat[fname][k]['A']):>11} {s(hat[fname][k]['L0'])} {s(hat[fname][k]['L1'])} | "
                  f"{np.median(d):+48.2f} [{d.min():+6.1f}, {d.max():+6.1f}]")
        print()
    print(f"RMSSD from annotations alone (N-N, phone rules), per record, ms: "
          + " ".join(f"{v:.1f}" for v in rms_ann))

# ======================================================================= main
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"# ./fiducial.py {' '.join(sys.argv[1:])}")
    print(f"# fs={FS:g} skip={args.skip_s:g}s; detector pan_tompkins.py unchanged; R window -100..+60 ms\n")
    if args.mode == "dual":
        res = run_dual(); report_dual(res)
    else:
        run_mitdb()
text = buf.getvalue(); print(text, end="")
name = (pathlib.Path(args.files[0]).stem.replace("_ring", "").replace("_ref", "")
        if args.mode == "dual" else "mitdb12")
out = pathlib.Path("analysis") / f"fiducial_{name}.txt"
out.write_text(text); print(f"saved {out}")
if args.mode == "dual":
    png = str(out).replace(".txt", ".png"); plot_dual(res, png); print(f"saved {png}")
