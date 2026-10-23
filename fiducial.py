#!/usr/bin/env python3
"""Which point in the QRS to time a beat from, and whether sub-sample
interpolation helps. Item 1 of the algorithm plan: HRV is built from beat
times, so their jitter sets how far any HRV figure can be trusted.

    ./fiducial.py dual  captures/<..>_ring.csv captures/<..>_ref.csv --chest ring [--zoom 35.5 39.5]
    ./fiducial.py mitdb [--dir data/mitdb]

The ring CSV comes first. Five timing points, each located around the beats the
detector finds (located from the detector's 5-15 Hz peak, `bp`):

  bp             index of max |5-15 Hz bandpassed| - timing point 1 (tp1), what
                 pan_tompkins.py reported up to 23 Oct 2026
  bp+parab       the same, with parabolic sub-sample interpolation
  R              peak of the dominant QRS deflection in the filtered ECG, with
                 ONE polarity per channel from the whole recording's median beat
  R+parab        the same, with parabolic sub-sample interpolation
  R+parab+guard  timing point 2 (tp2), the version proposed for the detectors:
                 - polarity from a ROLLING median beat (the previous 16 beats,
                   needing at least 8), so the phone never decides it beat by
                   beat. The sign is set only while one lobe of that median beat
                   is at least 1.5x the other; otherwise polarity is UNDECIDED
                   (on MIT-BIH 108, 24% of beats have lobes within 1.5x, and
                   picking a sign there moves the beat by a whole lobe)
                 - the R search window is detrended (a straight line through the
                   mean of its first and last 3 samples is subtracted), so
                   baseline wander cannot hand it a slope instead of a peak
                 - a maximum within 2 samples of either window edge is not a
                   peak: the beat falls back to bp+parab and is FLAGGED, which
                   keeps it out of every RR interval used for HRV
                 - beats while polarity is undecided are also fallback+flagged

Every RMSSD here is computed on a cleaned NN series: intervals outside
300-2000 ms or touching a flagged beat are invalid; a valid interval more than
20% away from the previous accepted interval is dropped; successive differences
are taken only between two accepted intervals that are adjacent in time.

PRIMARY validation - dual: finger and chest record the same heartbeats, so the
same timing point on both should give the same RR intervals. All timing points
are scored on one fixed set of matched beat pairs.

SECONDARY - mitdb: annotation times are a reference with their own jitter, not
ground truth. A three-cornered hat across annotation, lead 0 and lead 1
estimates each one's own jitter, assuming the three errors are independent
(v1 found that assumption does not hold - kept for comparison).

Saves analysis/fiducial_<name>_v2.txt (and .png for dual). v1 outputs are kept.
"""
import argparse, io, contextlib, pathlib, sys
import numpy as np
from scipy import signal as sps
import pan_tompkins

VERSION = "v2"
ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["dual", "mitdb"])
ap.add_argument("files", nargs="*")
ap.add_argument("--chest", choices=["ring", "ref"], default="ring",
                help="which of the two dual CSVs is the chest electrode")
ap.add_argument("--dir", default="data/mitdb")
ap.add_argument("--fs", type=float, default=256.0)
ap.add_argument("--skip-s", type=float, default=10.0)
ap.add_argument("--zoom", type=float, nargs=2, metavar=("T0", "T1"),
                help="dual: also plot this stretch (s) with the timing points marked")
args = ap.parse_args()
FS = args.fs
FIDS = ["bp", "bp+parab", "R", "R+parab", "R+parab+guard"]
FILTERS = ["zero-phase", "causal"]

# Window and polarity parameters, shared with the detectors once ported.
R_BEFORE_S, R_AFTER_S = 0.100, 0.060     # R search: 100 ms before .. 60 ms after the bp index
POL_KEEP, POL_MIN, POL_RATIO = 16, 8, 1.5 # rolling template: beats kept, needed, lobe ratio to decide
EDGE = 2                                   # a max this close to the window edge is not a peak
NN_STEP = 0.20                             # RR cleaning: max change from previous accepted
NN_SEED = 5                                # ...seeded from the median of this many valid intervals,
                                           # and re-seeded after this many consecutive drops

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

def detect_bp(y, fs):
    """Beat locations from the detector's 5-15 Hz peak. After the tp2 port the
    detector reports tp2 positions in `peaks` and keeps the 5-15 Hz ones in
    `bp_peaks`; before it, `peaks` is the 5-15 Hz peak."""
    pt = pan_tompkins.PanTompkins(fs)
    for v in y:
        pt.process(v)
    return np.array(getattr(pt, "bp_peaks", pt.peaks), dtype=int)

# ---------------------------------------------------------------- fiducials
def parabolic(v, k):
    """Vertex offset of the parabola through v[k-1..k+1], in samples (|d|<=0.5).
    0 when k is on an edge or is not a local maximum."""
    if k <= 0 or k >= len(v) - 1:
        return 0.0
    a, b, c = v[k - 1], v[k], v[k + 1]
    den = a - 2 * b + c
    if not (den < 0 and b >= a and b >= c):
        return 0.0
    return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))

def detrend(w):
    """Subtract the straight line through the means of the first and last 3 samples."""
    a, b = np.mean(w[:3]), np.mean(w[-3:])
    return w - (a + (b - a) * np.arange(len(w)) / (len(w) - 1))

def polarity_whole(y, det, fs):
    """v1: +1 or -1 from the dominant deflection of the whole recording's median beat."""
    w = int(0.10 * fs)
    segs = [y[d - w:d + w] for d in det if d - w >= 0 and d + w < len(y)]
    m = np.median(np.array(segs), axis=0)
    return 1.0 if m[np.argmax(np.abs(m))] > 0 else -1.0

def polarity_rolling(y, det, fs):
    """tp2: per-beat sign from the median of the PREVIOUS beats' windows (no
    beat votes on its own sign). 0 (undecided) until POL_MIN beats are in, and
    whenever neither lobe of the median beat is POL_RATIO x the other.
    Returns (signs, flips) - flips counts +1 <-> -1 changes."""
    lo, hi = int(R_BEFORE_S * fs), int(R_AFTER_S * fs)
    segs, signs, last, flips = [], np.zeros(len(det)), 0.0, 0
    for i, d in enumerate(det):
        cur = 0.0
        if len(segs) >= POL_MIN:
            t = detrend(np.median(np.array(segs), axis=0))
            pos, neg = t.max(), -t.min()
            if pos >= POL_RATIO * neg:
                cur = 1.0
            elif neg >= POL_RATIO * pos:
                cur = -1.0
        if cur != 0.0 and last != 0.0 and cur != last:
            flips += 1
        if cur != 0.0:
            last = cur
        signs[i] = cur
        if d - lo >= 0 and d + hi < len(y):
            segs.append(y[d - lo:d + hi + 1]); segs = segs[-POL_KEEP:]
    return signs, flips

def fiducials(y, det, fs):
    """Times in samples (float) per timing point, one per detection; NaN if the
    window runs off the signal. Also the tp2 flags and polarity diagnostics."""
    bp = np.abs(bandpassed(y, fs))
    s1 = polarity_whole(y, det, fs)
    s2, flips = polarity_rolling(y, det, fs)
    lo, hi = int(R_BEFORE_S * fs), int(R_AFTER_S * fs)
    out = {k: np.full(len(det), np.nan) for k in FIDS}
    flag = np.zeros(len(det), bool); why = {"undecided": 0, "edge": 0}
    for i, d in enumerate(det):
        out["bp"][i] = d
        out["bp+parab"][i] = d + parabolic(bp, d)
        if d - lo < 1 or d + hi >= len(y) - 1:
            continue
        w = s1 * y[d - lo:d + hi + 1]
        k = int(np.argmax(w))
        out["R"][i] = d - lo + k
        out["R+parab"][i] = d - lo + k + parabolic(w, k)
        # tp2
        if s2[i] == 0:
            out["R+parab+guard"][i] = out["bp+parab"][i]; flag[i] = True; why["undecided"] += 1
            continue
        wd = detrend(s2[i] * y[d - lo:d + hi + 1])
        k = int(np.argmax(wd))
        if k < EDGE or k > len(wd) - 1 - EDGE:
            out["R+parab+guard"][i] = out["bp+parab"][i]; flag[i] = True; why["edge"] += 1
            continue
        out["R+parab+guard"][i] = d - lo + k + parabolic(wd, k)
    pol = dict(whole=s1, decided=int(np.sum(s2 != 0)), flips=flips,
               agree=int(np.sum(s2 == s1)), n=len(det))
    return out, flag, why, pol

# --------------------------------------------------------------------- stats
def rsd(x):
    """Robust sd: 1.4826 x median absolute deviation."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")

def clean_nn(rr_ms, stats=None):
    """NN cleaning. rr_ms may hold NaN for intervals that touch a flagged beat
    or span a break. Returns (accepted mask, n_invalid, n_dropped_20pct).

    A valid interval (300-2000 ms) is dropped when it differs by more than 20%
    from the previous ACCEPTED interval, carried across invalid ones.
    Seeding: the reference starts as the median of the first NN_SEED valid
    intervals, not the first one - a single spurious first interval (two
    warm-up beats 328 ms apart on dual03) otherwise rejects every real interval
    after it. Recovery: after NN_SEED consecutive drops the reference is reset
    to their median, so a genuine step change in rate cannot lock it out."""
    rr_ms = np.asarray(rr_ms, float)
    valid = np.isfinite(rr_ms) & (rr_ms >= 300.0) & (rr_ms <= 2000.0)
    acc = np.zeros(len(rr_ms), bool); n_inv = int(np.sum(~valid)); n_drop = 0; reseeds = 0
    vi = np.flatnonzero(valid)
    if len(vi) == 0:
        return acc, n_inv, 0
    ref = float(np.median(rr_ms[vi[:NN_SEED]]))
    run = []
    for i in vi:
        m = rr_ms[i]
        if abs(m - ref) > NN_STEP * ref:
            n_drop += 1; run.append(m)
            if len(run) >= NN_SEED:
                ref = float(np.median(run)); run = []; reseeds += 1
            continue
        acc[i] = True; ref = m; run = []
    if stats is not None:
        stats["reseeds"] = stats.get("reseeds", 0) + reseeds
    return acc, n_inv, n_drop

def rmssd_clean(rr_ms):
    """RMSSD on the cleaned NN series; differences only between two accepted,
    adjacent intervals. Returns (rmssd, n_differences, n_invalid, n_dropped)."""
    rr_ms = np.asarray(rr_ms, float)
    acc, n_inv, n_drop = clean_nn(rr_ms)
    d = [rr_ms[i] - rr_ms[i - 1] for i in range(1, len(rr_ms)) if acc[i] and acc[i - 1]]
    r = float(np.sqrt(np.mean(np.square(d)))) if d else float("nan")
    return r, len(d), n_inv, n_drop

def intervals(t_ms, flag):
    """RR between successive beats; NaN where either beat is flagged."""
    rr = np.diff(t_ms)
    if flag is not None:
        rr[flag[:-1] | flag[1:]] = np.nan
    return rr

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
            det = detect_bp(y, FS)
            fid, flag, why, pol = fiducials(y, det, FS)
            ch[site] = dict(h0=h0, det=det, fid=fid, flag=flag, why=why, pol=pol, y=y)
        # Fix the beat pairs once, from the detector's own beat times, so every
        # timing point is scored on exactly the same beats.
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
    print("beat dt = finger - chest beat time on matched beats, median removed. 'jitter' excludes")
    print("pairs off by >20 ms (gross mislocations, counted separately). For R+parab+guard, pairs")
    print("where either beat is flagged are left out of dt and RR and counted under 'flag'.")
    print("RMSSD columns use the cleaned NN series (see the docstring); 'drop' is intervals")
    print("removed by the 20% rule, as chest/finger.\n")
    for fname in FILTERS:
        r = res[fname]; ch = r["ch"]; pairs = r["pairs"]
        print(f"=== {fname} filter ===")
        print(f"beats detected chest {r['n_det'][0]}, finger {r['n_det'][1]}; matched pairs {len(pairs)}")
        for site in ("chest", "finger"):
            p, w = ch[site]["pol"], ch[site]["why"]
            print(f"  {site:6} polarity: whole-recording {p['whole']:+.0f}; rolling decided on "
                  f"{p['decided']}/{p['n']} beats, agrees on {p['agree']}, flips {p['flips']}; "
                  f"tp2 flagged {int(ch[site]['flag'].sum())} (undecided {w['undecided']}, edge {w['edge']})")
        ic = np.array([p[0] for p in pairs]); jf = np.array([p[1] for p in pairs])
        cons = np.flatnonzero((np.diff(ic) == 1) & (np.diff(jf) == 1))
        print(f"{'timing point':14} {'dt sd':>7} {'jitter':>7} {'>20ms':>5} {'flag':>4} | "
              f"{'RR diff sd':>10} {'LoA':>14} | {'RMSSD ch':>8} {'fing':>5} {'diff':>5} {'n':>4} {'drop':>5} | "
              f"{'all-beats ch':>12} {'fing':>5} {'drop':>5}")
        r["rows"] = {}
        for k in FIDS:
            g = k == "R+parab+guard"
            fc = ch["chest"]["flag"] if g else np.zeros(len(ch["chest"]["det"]), bool)
            ff = ch["finger"]["flag"] if g else np.zeros(len(ch["finger"]["det"]), bool)
            t_c = ch["chest"]["fid"][k] / FS * 1000; t_f = ch["finger"]["fid"][k] / FS * 1000
            okp = ~(fc[ic] | ff[jf])
            dt = t_f[jf] - t_c[ic]; dt = dt - np.median(dt[okp]); dtu = dt[okp]
            big = np.abs(dtu) > 20
            # RR on consecutive matched pairs, NaN where a flagged beat is involved
            rr_c = t_c[ic[cons + 1]] - t_c[ic[cons]]; rr_f = t_f[jf[cons + 1]] - t_f[jf[cons]]
            bad = fc[ic[cons]] | fc[ic[cons + 1]] | ff[jf[cons]] | ff[jf[cons + 1]]
            drr = (rr_f - rr_c)[~bad]; bias, sd = float(np.mean(drr)), float(np.std(drr, ddof=1))
            # Cleaning per channel on its FULL beat series (as the phone would),
            # then like-for-like differences where both channels accepted both
            # adjacent intervals.
            rr_full_c = intervals(t_c, fc); rr_full_f = intervals(t_f, ff)
            acc_c, _, drop_c = clean_nn(rr_full_c); acc_f, _, drop_f = clean_nn(rr_full_f)
            sd_c, sd_f = [], []
            for q in range(1, len(cons)):
                if cons[q] != cons[q - 1] + 1:
                    continue
                i1, i2 = ic[cons[q - 1]], ic[cons[q]]      # chest interval starts
                j1, j2 = jf[cons[q - 1]], jf[cons[q]]
                if acc_c[i1] and acc_c[i2] and acc_f[j1] and acc_f[j2]:
                    sd_c.append(rr_full_c[i2] - rr_full_c[i1]); sd_f.append(rr_full_f[j2] - rr_full_f[j1])
            rm_c = float(np.sqrt(np.mean(np.square(sd_c)))); rm_f = float(np.sqrt(np.mean(np.square(sd_f))))
            ac, _, _, adc = rmssd_clean(rr_full_c); af, _, _, adf = rmssd_clean(rr_full_f)
            r["rows"][k] = dict(dt=dtu)
            print(f"{k:14} {np.std(dtu, ddof=1):5.2f}ms {np.std(dtu[~big], ddof=1):5.2f}ms {int(big.sum()):5d} "
                  f"{int((~okp).sum()):4d} | {sd:8.2f}ms {bias-1.96*sd:+6.1f}..{bias+1.96*sd:+5.1f} | "
                  f"{rm_c:6.1f}ms {rm_f:5.1f} {rm_f-rm_c:+5.1f} {len(sd_c):4d} {drop_c:2d}/{drop_f:<2d} | "
                  f"{ac:10.1f}ms {af:5.1f} {adc:2d}/{adf:<2d}")
            if 0 < big.sum() <= 6:
                tt = (ch["chest"]["fid"][k][ic] / FS)[okp][big]
                print(f"{'':14} gross: " + ", ".join(f"{v:+.0f} ms at {t:.1f} s" for t, v in zip(tt, dtu[big])))
            elif big.sum():
                print(f"{'':14} gross: {int(big.sum())} pairs, dt {dtu[big].min():+.0f}..{dtu[big].max():+.0f} ms")
        print()

def plot_dual(res, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, len(FIDS), figsize=(18, 6.2), sharex=True)
    bins = np.arange(-40, 41, 1.0)
    for row, fname in enumerate(FILTERS):
        for col, k in enumerate(FIDS):
            ax = axes[row, col]; dt = res[fname]["rows"][k]["dt"]
            ax.hist(np.clip(dt, -40, 40), bins=bins, color="#2a78d6" if "R" in k else "#eb6834")
            ax.set_title(f"{fname} | {k}\nsd {np.std(dt, ddof=1):.1f} ms", fontsize=10)
            ax.axvline(0, color="0.6", lw=.8)
            if row == 1: ax.set_xlabel("finger - chest, ms")
    fig.suptitle("Finger minus chest beat time on the same beats (median removed, clipped at +-40 ms; "
                 "R+parab+guard excludes flagged beats)", fontsize=12)
    fig.tight_layout(); fig.savefig(png, dpi=110)

def plot_zoom(res, t0, t1, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(15, 6.4), sharex=True)
    for col, fname in enumerate(FILTERS):
        for row, site in enumerate(("chest", "finger")):
            ax = axes[row, col]; c = res[fname]["ch"][site]; y = c["y"]
            s = c["pol"]["whole"]; t = np.arange(len(y)) / FS; m = (t >= t0) & (t <= t1)
            ax.plot(t[m], s * y[m], lw=1.1, color="#2a78d6" if site == "chest" else "#eb6834")
            for k, mk, kw in (("bp", "v", dict(mfc="none", color="0.45")),
                              ("R+parab", "o", dict(mfc="none", color="k")),
                              ("R+parab+guard", "x", dict(color="#c0392b", mew=2))):
                tt = c["fid"][k] / FS; sel = (tt >= t0) & (tt <= t1)
                ax.plot(tt[sel], np.interp(tt[sel], t, s * y), mk, ms=8, label=k, **kw)
            fl = c["det"][c["flag"]] / FS
            for f in fl[(fl >= t0) & (fl <= t1)]:
                ax.axvline(f, color="#c0392b", ls=":", lw=1)
            ax.set_title(f"{site}, {fname} filter (polarity-corrected); dotted = tp2 flagged", fontsize=10)
            if row == 0 and col == 0: ax.legend(fontsize=8)
    for ax in axes[1]: ax.set_xlabel("s")
    fig.tight_layout(); fig.savefig(png, dpi=100)

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
    print("detections matched to annotations within 150 ms. For R+parab+guard, flagged beats are")
    print("left out of the timing statistics and counted. Three-cornered hat on robust variances")
    print("(1.4826 x MAD)^2, per record, then the median across records; 'neg' = the estimate came")
    print("out negative (the independence assumption fails).\n")
    hat = {f: {k: {"A": [], "L0": [], "L1": []} for k in FIDS} for f in FILTERS}
    rms = {f: {k: [] for k in FIDS} for f in FILTERS}
    rms_ann = []
    print("robust sd(lead-0 timing point - annotation), ms - mixes our jitter with the annotation's;")
    print(">20 = matched beats off by more than 20 ms (lead 0); flag = tp2 beats flagged; pol = rolling")
    print("polarity decided/agrees-with-whole-recording/flips")
    print(f"{'rec':>4} {'beats':>6} | {'filter':10} " + " ".join(f"{k:>13}" for k in FIDS)
          + f" | {'>20 R+p':>7} {'>20 tp2':>7} {'flag':>5} {'pol':>14}")
    for rec in recs:
        r = wfdb.rdrecord(f"{args.dir}/{rec}"); ann = wfdb.rdann(f"{args.dir}/{rec}", "atr")
        fs0 = float(r.fs)
        n_new = int(round(r.p_signal.shape[0] * FS / fs0))
        x0 = sps.resample(r.p_signal[:, 0].astype(float), n_new)
        x1 = sps.resample(r.p_signal[:, 1].astype(float), n_new)
        sym = np.array(ann.symbol); samp = np.array(ann.sample)
        bidx = np.flatnonzero([s in BEAT for s in sym])
        nmask = np.zeros(len(sym), bool)
        for q in range(1, len(bidx) - 1):
            k = bidx[q]
            if sym[k] in AAMI_N and sym[bidx[q - 1]] in AAMI_N and sym[bidx[q + 1]] in AAMI_N:
                nmask[k] = True
        ann_t = samp[nmask] / fs0                   # seconds, unrounded
        for fname in FILTERS:
            causal = fname == "causal"
            y0 = filt(x0, FS, 60.0, False, causal); y1 = filt(x1, FS, 60.0, False, causal)
            det = detect_bp(y0, FS)
            f0, fl0, _, pol0 = fiducials(y0, det, FS); f1, fl1, _, _ = fiducials(y1, det, FS)
            pairs = greedy(ann_t, det / FS, 0.15)
            ia = np.array([p[0] for p in pairs], dtype=int); jd = np.array([p[1] for p in pairs], dtype=int)
            fin = np.array([all(np.isfinite(f0[k][j]) and np.isfinite(f1[k][j]) for k in FIDS) for j in jd],
                           dtype=bool)
            ia, jd = ia[fin], jd[fin]
            if len(ia) < 30:
                print(f"{rec:>4} skipped ({fname}): fewer than 30 matched class-N beats"); continue
            A = ann_t[ia] * 1000
            cells = []
            for k in FIDS:
                use = ~(fl0[jd] | fl1[jd]) if k == "R+parab+guard" else np.ones(len(jd), bool)
                L0 = f0[k][jd] / FS * 1000; L1 = f1[k][jd] / FS * 1000
                v = lambda u: rsd(u[use]) ** 2
                vA0, vA1, v01 = v(L0 - A), v(L1 - A), v(L0 - L1)
                hat[fname][k]["A"].append((vA0 + vA1 - v01) / 2)
                hat[fname][k]["L0"].append((vA0 + v01 - vA1) / 2)
                hat[fname][k]["L1"].append((vA1 + v01 - vA0) / 2)
                cells.append(rsd((L0 - A)[use]))
                if k == "R+parab":
                    e = L0 - A; gross_rp = int(np.sum(np.abs(e - np.median(e)) > 20))
                if k == "R+parab+guard":
                    e = (L0 - A)[use]; gross_g = int(np.sum(np.abs(e - np.median(e)) > 20))
                # RMSSD on runs of consecutive matched beats: timing point vs annotation,
                # both cleaned by the same rules; flagged beats break the fiducial series
                fbad = fl0[jd] if k == "R+parab+guard" else np.zeros(len(jd), bool)
                rf, ra = [], []
                for q in range(len(ia) - 1):
                    if ia[q + 1] != ia[q] + 1:
                        rf.append(np.nan); ra.append(np.nan); continue
                    ra.append(A[q + 1] - A[q])
                    rf.append(np.nan if (fbad[q] or fbad[q + 1]) else L0[q + 1] - L0[q])
                mf = rmssd_clean(rf)[0]; ma = rmssd_clean(ra)[0]
                rms[fname][k].append(mf - ma)
                if fname == "zero-phase" and k == "bp":
                    rms_ann.append(ma)
            nflag = int(fl0[jd].sum())
            print(f"{rec:>4} {len(ia):6d} | {fname:10} " + " ".join(f"{v:13.2f}" for v in cells)
                  + f" | {gross_rp:7d} {gross_g:7d} {nflag:5d} "
                  f"{pol0['decided']:>5}/{pol0['agree']}/{pol0['flips']}")
    print()
    for fname in FILTERS:
        print(f"=== {fname}: three-cornered hat, own jitter sd (ms), median over records ===")
        print(f"{'timing point':14} {'annotation':>11} {'lead 0':>8} {'lead 1':>8} | "
              f"{'RMSSD(tp) - RMSSD(annotation), ms, median':>42} {'[min, max]':>16}")
        for k in FIDS:
            def s(lst):
                m = float(np.median(lst)); return f"{np.sqrt(m):8.2f}" if m > 0 else "     neg"
            d = np.array(rms[fname][k])
            print(f"{k:14} {s(hat[fname][k]['A']):>11} {s(hat[fname][k]['L0'])} {s(hat[fname][k]['L1'])} | "
                  f"{np.median(d):+42.2f} [{d.min():+6.1f}, {d.max():+6.1f}]")
        print()
    print("RMSSD from annotations alone (class-N runs, cleaned), per record, ms: "
          + " ".join(f"{v:.1f}" for v in rms_ann))

# ======================================================================= main
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"# ./fiducial.py {' '.join(sys.argv[1:])}   (analysis {VERSION})")
    print(f"# fs={FS:g} skip={args.skip_s:g}s; R window -{R_BEFORE_S*1000:.0f}..+{R_AFTER_S*1000:.0f} ms; "
          f"rolling polarity keep {POL_KEEP} / need {POL_MIN} / lobe ratio {POL_RATIO}x; edge {EDGE}; "
          f"NN step {NN_STEP:.0%}")
    print(f"# beat locations from the detector's 5-15 Hz peak "
          f"({'bp_peaks' if hasattr(pan_tompkins.PanTompkins(FS), 'bp_peaks') else 'peaks'})\n")
    if args.mode == "dual":
        res = run_dual(); report_dual(res)
    else:
        run_mitdb()
text = buf.getvalue(); print(text, end="")
name = (pathlib.Path(args.files[0]).stem.replace("_ring", "").replace("_ref", "")
        if args.mode == "dual" else "mitdb12")
out = pathlib.Path("analysis") / f"fiducial_{name}_{VERSION}.txt"
out.write_text(text); print(f"saved {out}")
if args.mode == "dual":
    png = str(out).replace(".txt", ".png"); plot_dual(res, png); print(f"saved {png}")
    if args.zoom:
        z = str(out).replace(".txt", f"_zoom_{args.zoom[0]:g}-{args.zoom[1]:g}s.png")
        plot_zoom(res, args.zoom[0], args.zoom[1], z); print(f"saved {z}")
