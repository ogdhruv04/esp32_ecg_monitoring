#!/usr/bin/env python3
"""Which point in the QRS to time a beat from, and how well each one serves HRV.

    ./fiducial.py dual  captures/<..>_ring.csv captures/<..>_ref.csv --chest ring [--zoom T0 T1]
    ./fiducial.py mitdb [--dir data/mitdb] [--records 100 101 ...] [--label dev12]

The ring CSV comes first. Six timing points, all on the same detected beats:

  bp        index of max |5-15 Hz bandpassed| - timing point 1 (tp1), what
            pan_tompkins.py reported up to 23 Oct 2026
  bp+parab  the same, with parabolic sub-sample interpolation
  R         peak of the dominant QRS deflection in the filtered ECG, with ONE
            polarity per channel from the whole recording's median beat
  R+parab   the same, with parabolic sub-sample interpolation
  tp2       the detector's own positions and flags (pan_tompkins.py) with the
            per-beat correlation check OFF - the version approved on 23 Oct
  tp2.1     the same with the check ON (CORR_MIN in tp2_config.json)

bp, bp+parab, R and R+parab are computed here around the detector's 5-15 Hz
peaks (its `bp_peaks`). tp2 and tp2.1 are not re-implemented: they are what
the detector reports, so this tests the code that ships. Analysis v2 emulated
tp2 offline; its outputs and code are kept in git history.

HRV. Every RMSSD uses the detector's cleaning (pan_tompkins.clean_nn): one
interval per pair of consecutive beats, NaN when either beat is flagged;
300-2000 ms; a valid interval more than 20% from the previous accepted one is
dropped (median seed, re-seed after 5 drops); differences only between two
accepted, adjacent intervals. COVERAGE is reported next to every RMSSD: the
share of beats whose preceding interval survives into the NN series.

PRIMARY validation - dual: finger and chest record the same heartbeats, so the
same timing point on both should give the same RR intervals.

SECONDARY - mitdb: annotation times are a reference with their own jitter, not
ground truth. The record's MLII lead is used where it exists (otherwise
channel 0), the other channel is lead 1 for the three-cornered hat.

Saves analysis/fiducial_<name>_v3.txt (and .png for dual).
"""
import argparse, io, contextlib, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs under python -I
import numpy as np
from scipy import signal as sps
import pan_tompkins as PT

VERSION = "v3"
ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["dual", "mitdb"])
ap.add_argument("files", nargs="*")
ap.add_argument("--chest", choices=["ring", "ref"], default="ring",
                help="which of the two dual CSVs is the chest electrode")
ap.add_argument("--dir", default="data/mitdb")
ap.add_argument("--records", nargs="*", help="mitdb: records to use (default: every .hea in --dir)")
ap.add_argument("--label", default=None, help="mitdb: output name, e.g. dev12 or heldout36")
ap.add_argument("--fs", type=float, default=256.0)
ap.add_argument("--skip-s", type=float, default=10.0)
ap.add_argument("--zoom", type=float, nargs=2, metavar=("T0", "T1"),
                help="dual: also plot this stretch (s) with the timing points marked")
args = ap.parse_args()
FS = args.fs
FIDS = ["bp", "bp+parab", "R", "R+parab", "tp2", "tp2.1"]
DETECTOR = {"tp2", "tp2.1"}
FILTERS = ["zero-phase", "causal"]
C = PT.CONFIG["detector"]          # window sizes; tp3 kept them

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
        q = PT._rbj(kind, f0, 0.7071, fs)
        out = sps.lfilter(q.b, (1.0,) + q.a, out)
    return out

def run_detector(y, fs, check):
    pt = PT.PanTompkins(fs, timing="tp2.1")      # this script compares tp2 and tp2.1; tp3: evaluate_tp3.py
    if not check:
        pt.CORR_MIN = None
    for v in y:
        pt.process(v)
    return (np.array(pt.bp_peaks, dtype=int), np.array(pt.peaks, dtype=float),
            np.array([b["flagged"] for b in pt.beats], dtype=bool), pt.corr_flagged)

# ---------------------------------------------------------------- fiducials
def parabolic(v, k):
    if k <= 0 or k >= len(v) - 1:
        return 0.0
    return PT._parabolic(v[k - 1], v[k], v[k + 1])

def polarity_whole(y, det, fs):
    """+1 or -1 from the dominant deflection of the whole recording's median beat."""
    w = int(0.10 * fs)
    segs = [y[d - w:d + w] for d in det if d - w >= 0 and d + w < len(y)]
    m = np.median(np.array(segs), axis=0)
    return 1.0 if m[np.argmax(np.abs(m))] > 0 else -1.0

def timing_points(y, fs):
    """{name: positions}, {name: flags} for all six timing points on one set of
    beats, plus the number of beats the correlation check flagged."""
    det, p2, f2, _ = run_detector(y, fs, check=False)
    det1, p21, f21, ncorr = run_detector(y, fs, check=True)
    assert np.array_equal(det, det1), "the correlation check must not change detection"
    bp = np.abs(bandpassed(y, fs))
    s1 = polarity_whole(y, det, fs)
    lo, hi = int(C["R_BEFORE_S"] * fs), int(C["R_AFTER_S"] * fs)
    pos = {k: np.full(len(det), np.nan) for k in FIDS}
    for i, d in enumerate(det):
        pos["bp"][i] = d
        pos["bp+parab"][i] = d + parabolic(bp, d)
        if d - lo < 1 or d + hi >= len(y) - 1:
            continue
        w = s1 * y[d - lo:d + hi + 1]
        k = int(np.argmax(w))
        pos["R"][i] = d - lo + k
        pos["R+parab"][i] = d - lo + k + parabolic(w, k)
    pos["tp2"], pos["tp2.1"] = p2, p21
    flags = {k: np.zeros(len(det), bool) for k in FIDS}
    flags["tp2"], flags["tp2.1"] = f2, f21
    return det, pos, flags, s1, ncorr

# --------------------------------------------------------------------- stats
def rsd(x):
    """Robust sd: 1.4826 x median absolute deviation."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")

def series(t_ms, flag):
    """One interval per pair of consecutive beats; NaN where either is flagged."""
    rr = np.diff(t_ms)
    rr[flag[:-1] | flag[1:]] = np.nan
    return rr

def hrv(rr):
    """(rmssd or nan, coverage, dropped) by the detector's rules."""
    rm, _, drop, cov = PT.rmssd_nn(list(rr))
    return (float("nan") if rm is None else rm), cov, drop

def greedy(ref_t, test_t, tol):
    """One-to-one nearest matching within tol (same rule as EC57 / agreement.py)."""
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
            det, pos, flags, s1, ncorr = timing_points(y, FS)
            ch[site] = dict(h0=h0, det=det, pos=pos, flags=flags, sign=s1, ncorr=ncorr, y=y)
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
              if all(np.isfinite(ch["chest"]["pos"][k][ic]) and np.isfinite(ch["finger"]["pos"][k][jf])
                     for k in FIDS)]
        res[fname] = dict(ch=ch, pairs=ok, n_det=(len(tc), len(tf)))
    return res

def report_dual(res):
    print("dt = finger - chest beat time on matched beats, median removed; 'jitter' excludes pairs")
    print("off by >20 ms (counted under >20ms). Pairs with a flagged beat are left out of dt and RR")
    print("and counted under 'flag'. RMSSD is on each channel's cleaned NN series over ALL its beats;")
    print("'cov' = share of that channel's beats whose interval is used; 'like-for-like' uses only")
    print("successive differences where both channels kept both intervals.\n")
    for fname in FILTERS:
        r = res[fname]; ch = r["ch"]; pairs = r["pairs"]
        print(f"=== {fname} filter ===")
        print(f"beats detected chest {r['n_det'][0]}, finger {r['n_det'][1]}; matched pairs {len(pairs)}; "
              f"whole-recording polarity chest {ch['chest']['sign']:+.0f}, finger {ch['finger']['sign']:+.0f}; "
              f"tp2.1 check flagged chest {ch['chest']['ncorr']}, finger {ch['finger']['ncorr']}")
        ic = np.array([p[0] for p in pairs]); jf = np.array([p[1] for p in pairs])
        cons = np.flatnonzero((np.diff(ic) == 1) & (np.diff(jf) == 1))
        print(f"{'timing point':12} {'dt sd':>6} {'jitter':>6} {'>20ms':>5} {'flag':>4} | {'RR LoA':>13} | "
              f"{'RMSSD chest':>11} {'cov':>4} {'finger':>6} {'cov':>4} | {'like-for-like ch / fing':>23} {'n':>4}")
        r["rows"] = {}
        for k in FIDS:
            fc = ch["chest"]["flags"][k]; ff = ch["finger"]["flags"][k]
            t_c = ch["chest"]["pos"][k] / FS * 1000; t_f = ch["finger"]["pos"][k] / FS * 1000
            okp = ~(fc[ic] | ff[jf])
            dt = t_f[jf] - t_c[ic]; dt = dt - np.median(dt[okp]); dtu = dt[okp]
            big = np.abs(dtu) > 20
            rr_c = t_c[ic[cons + 1]] - t_c[ic[cons]]; rr_f = t_f[jf[cons + 1]] - t_f[jf[cons]]
            bad = fc[ic[cons]] | fc[ic[cons + 1]] | ff[jf[cons]] | ff[jf[cons + 1]]
            drr = (rr_f - rr_c)[~bad]; bias, sd = float(np.mean(drr)), float(np.std(drr, ddof=1))
            sc, sf = series(t_c, fc), series(t_f, ff)
            rm_c, cov_c, _ = hrv(sc); rm_f, cov_f, _ = hrv(sf)
            acc_c, _ = PT.clean_nn(list(sc)); acc_f, _ = PT.clean_nn(list(sf))
            dc, df = [], []
            for q in range(1, len(cons)):
                if cons[q] != cons[q - 1] + 1:
                    continue
                i1, i2 = ic[cons[q - 1]], ic[cons[q]]; j1, j2 = jf[cons[q - 1]], jf[cons[q]]
                if acc_c[i1] and acc_c[i2] and acc_f[j1] and acc_f[j2]:
                    dc.append(sc[i2] - sc[i1]); df.append(sf[j2] - sf[j1])
            lc = float(np.sqrt(np.mean(np.square(dc)))) if dc else float("nan")
            lf = float(np.sqrt(np.mean(np.square(df)))) if df else float("nan")
            r["rows"][k] = dict(dt=dtu)
            print(f"{k:12} {np.std(dtu, ddof=1):6.2f} {np.std(dtu[~big], ddof=1):6.2f} {int(big.sum()):5d} "
                  f"{int((~okp).sum()):4d} | {bias-1.96*sd:+6.1f}..{bias+1.96*sd:+5.1f} | "
                  f"{rm_c:9.1f}ms {100*cov_c:3.0f}% {rm_f:5.1f}ms {100*cov_f:3.0f}% | "
                  f"{lc:10.1f} / {lf:5.1f} ms {len(dc):4d}")
            if 0 < big.sum() <= 6:
                tt = (ch["chest"]["pos"][k][ic] / FS)[okp][big]
                print(f"{'':12} gross: " + ", ".join(f"{v:+.0f} ms at {t:.1f} s" for t, v in zip(tt, dtu[big])))
            elif big.sum():
                print(f"{'':12} gross: {int(big.sum())} pairs, dt {dtu[big].min():+.0f}..{dtu[big].max():+.0f} ms")
        print()

def plot_dual(res, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, len(FIDS), figsize=(20, 6.2), sharex=True)
    bins = np.arange(-40, 41, 1.0)
    for row, fname in enumerate(FILTERS):
        for col, k in enumerate(FIDS):
            ax = axes[row, col]; dt = res[fname]["rows"][k]["dt"]
            ax.hist(np.clip(dt, -40, 40), bins=bins, color="#2a78d6" if k[0] in "Rt" else "#eb6834")
            ax.set_title(f"{fname} | {k}\nsd {np.std(dt, ddof=1):.1f} ms", fontsize=10)
            ax.axvline(0, color="0.6", lw=.8)
            if row == 1: ax.set_xlabel("finger - chest, ms")
    fig.suptitle("Finger minus chest beat time on the same beats (median removed, clipped at +-40 ms; "
                 "flagged beats excluded)", fontsize=12)
    fig.tight_layout(); fig.savefig(png, dpi=110)

def plot_zoom(res, t0, t1, png):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(15, 6.4), sharex=True)
    for col, fname in enumerate(FILTERS):
        for row, site in enumerate(("chest", "finger")):
            ax = axes[row, col]; c = res[fname]["ch"][site]; y = c["y"]
            s = c["sign"]; t = np.arange(len(y)) / FS; m = (t >= t0) & (t <= t1)
            ax.plot(t[m], s * y[m], lw=1.1, color="#2a78d6" if site == "chest" else "#eb6834")
            for k, mk, kw in (("bp", "v", dict(mfc="none", color="0.45")),
                              ("R+parab", "o", dict(mfc="none", color="k")),
                              ("tp2.1", "x", dict(color="#c0392b", mew=2))):
                tt = c["pos"][k] / FS; sel = (tt >= t0) & (tt <= t1)
                ax.plot(tt[sel], np.interp(tt[sel], t, s * y), mk, ms=8, label=k, **kw)
            fl = c["det"][c["flags"]["tp2.1"]] / FS
            for f in fl[(fl >= t0) & (fl <= t1)]:
                ax.axvline(f, color="#c0392b", ls=":", lw=1)
            ax.set_title(f"{site}, {fname} filter (polarity-corrected); dotted = tp2.1 flagged", fontsize=10)
            if row == 0 and col == 0: ax.legend(fontsize=8)
    for ax in axes[1]: ax.set_xlabel("s")
    fig.tight_layout(); fig.savefig(png, dpi=100)

# ====================================================================== mitdb
def run_mitdb():
    import wfdb
    BEAT = set("NLRejAaJSVEFP/fQ")
    AAMI_N = set("NLRej")      # AAMI class N: normally conducted beats, incl. bundle branch block
    recs = args.records or sorted(p.stem for p in pathlib.Path(args.dir).glob("*.hea"))
    print(f"MIT-BIH, {len(recs)} records from {args.dir}: {' '.join(recs)}")
    print("Front end as benchmark_mitdb.py: resampled to 256 Hz, 0.5-40 Hz, single 60 Hz notch. Lead 0 is")
    print("MLII where the record has it, else channel 0; lead 1 is the other channel. Annotation times are")
    print("kept unrounded. Timing and RMSSD use AAMI class-N beats (N L R e j) whose neighbouring beats")
    print("are also class N, matched to detections within 150 ms. Flagged beats are left out of timing")
    print("statistics and break the RR series. RMSSD error = RMSSD(timing point) - RMSSD(annotations),")
    print("both on runs of consecutive matched class-N beats, both cleaned by the detector's rules.")
    print("COVERAGE = beats whose interval is used in that RMSSD / all annotated beats in the record.\n")
    SHOW = ["bp", "R+parab", "tp2", "tp2.1"]
    hat = {f: {k: {"A": [], "L0": [], "L1": []} for k in FIDS} for f in FILTERS}
    agg = {f: {k: {"sd": [], "err": [], "cov": []} for k in FIDS} for f in FILTERS}
    ann_cov = []
    for fname in FILTERS:
        print(f"=== {fname} filter: per record, sd(lead-0 timing - annotation) ms / RMSSD error ms / coverage % ===")
        print(f"{'rec':>4} {'lead':>5} {'beats':>6} {'ann RMSSD':>9} {'cov':>4} | "
              + " | ".join(f"{k:^21}" for k in SHOW) + " | check flagged")
        for rec in recs:
            r = wfdb.rdrecord(f"{args.dir}/{rec}"); ann = wfdb.rdann(f"{args.dir}/{rec}", "atr")
            fs0 = float(r.fs)
            names = list(r.sig_name)
            c0 = names.index("MLII") if "MLII" in names else 0
            c1 = 1 - c0
            n_new = int(round(r.p_signal.shape[0] * FS / fs0))
            x0 = sps.resample(r.p_signal[:, c0].astype(float), n_new)
            x1 = sps.resample(r.p_signal[:, c1].astype(float), n_new)
            sym = np.array(ann.symbol); samp = np.array(ann.sample)
            bidx = np.flatnonzero([s in BEAT for s in sym])
            n_beats_all = len(bidx)
            nmask = np.zeros(len(sym), bool)
            for q in range(1, len(bidx) - 1):
                k = bidx[q]
                if sym[k] in AAMI_N and sym[bidx[q - 1]] in AAMI_N and sym[bidx[q + 1]] in AAMI_N:
                    nmask[k] = True
            ann_t = samp[nmask] / fs0
            causal = fname == "causal"
            y0 = filt(x0, FS, 60.0, False, causal); y1 = filt(x1, FS, 60.0, False, causal)
            det, p0, fl0, _, ncorr = timing_points(y0, FS)
            # lead 1: the same beats, located on lead 1 (offline variants only;
            # the detector's tp2 needs its own beats, so lead 1 uses the
            # detector on lead 1 for tp2/tp2.1 and matches by nearest beat)
            det1, p1, fl1, _, _ = timing_points(y1, FS)
            pairs = greedy(ann_t, det / FS, 0.15)
            ia = np.array([p[0] for p in pairs], dtype=int); jd = np.array([p[1] for p in pairs], dtype=int)
            if len(ia) < 30:
                print(f"{rec:>4} skipped: fewer than 30 matched class-N beats"); continue
            # lead-1 beat for each lead-0 beat, within 150 ms
            pr1 = dict(greedy(det / FS, det1 / FS, 0.15))   # {lead-0 beat: lead-1 beat}
            A = ann_t[ia] * 1000
            cells = []
            for k in FIDS:
                L0 = p0[k][jd] / FS * 1000
                use = ~fl0[k][jd] & np.isfinite(L0)
                L1 = np.array([p1[k][pr1[j]] / FS * 1000 if j in pr1 and not fl1[k][pr1[j]] else np.nan
                               for j in jd])
                v = lambda u: rsd(u[use & np.isfinite(u)]) ** 2
                vA0, vA1, v01 = v(L0 - A), v(L1 - A), v(L0 - L1)
                hat[fname][k]["A"].append((vA0 + vA1 - v01) / 2)
                hat[fname][k]["L0"].append((vA0 + v01 - vA1) / 2)
                hat[fname][k]["L1"].append((vA1 + v01 - vA0) / 2)
                rf, ra = [], []
                for q in range(len(ia) - 1):
                    if ia[q + 1] != ia[q] + 1:
                        rf.append(np.nan); ra.append(np.nan); continue
                    ra.append(A[q + 1] - A[q])
                    rf.append(L0[q + 1] - L0[q] if use[q] and use[q + 1] else np.nan)
                acc_f, _ = PT.clean_nn(rf); acc_a, _ = PT.clean_nn(ra)
                mf = hrv(rf)[0]; ma = hrv(ra)[0]
                cov = int(sum(acc_f)) / max(1, n_beats_all - 1)
                sdv = rsd((L0 - A)[use])
                agg[fname][k]["sd"].append(sdv); agg[fname][k]["err"].append(mf - ma)
                agg[fname][k]["cov"].append(cov)
                if k in SHOW:
                    cells.append(f"{sdv:5.2f} {mf - ma:+6.2f} {100*cov:4.0f}%")
            acov = int(sum(acc_a)) / max(1, n_beats_all - 1)
            if fname == "zero-phase":
                ann_cov.append(acov)
            print(f"{rec:>4} {names[c0]:>5} {len(ia):6d} {ma:7.1f}ms {100*acov:3.0f}% | "
                  + " | ".join(f"{c:^21}" for c in cells) + f" | {ncorr}")
        print()
    for fname in FILTERS:
        print(f"=== {fname}: summary over records (median [min, max]) ===")
        print(f"{'timing point':12} {'sd vs annotation, ms':>24} {'RMSSD error, ms':>27} {'coverage %':>22} | "
              f"three-cornered hat sd ms: annotation / lead 0 / lead 1")
        for k in FIDS:
            a = agg[fname][k]
            def mm(v, f="{:+.2f}"):
                v = np.array(v, float); v = v[np.isfinite(v)]
                return (f.format(np.median(v)) + " [" + f.format(v.min()) + ", " + f.format(v.max()) + "]") if len(v) else "n/a"
            def s(lst):
                m = float(np.nanmedian(lst)); return f"{np.sqrt(m):.2f}" if m > 0 else "neg"
            print(f"{k:12} {mm(a['sd'], '{:.2f}'):>24} {mm(a['err']):>27} "
                  f"{mm(100*np.array(a['cov']), '{:.0f}'):>22} | "
                  f"{s(hat[fname][k]['A'])} / {s(hat[fname][k]['L0'])} / {s(hat[fname][k]['L1'])}")
        print()
    print("RMSSD errors are NaN-skipped in the summary; a record whose RMSSD is withheld (fewer than "
          f"{PT.MIN_BEATS_FOR_HRV} accepted intervals) shows nan in its row.")

# ======================================================================= main
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"# ./fiducial.py {' '.join(sys.argv[1:])}   (analysis {VERSION})")
    print(f"# detector config {PT.CONFIG['version']} (tp2_config.json): {PT.CONFIG['detector']}")
    print(f"# HRV: {PT.CONFIG['hrv']}\n")
    if args.mode == "dual":
        res = run_dual(); report_dual(res)
    else:
        run_mitdb()
text = buf.getvalue(); print(text, end="")
if args.mode == "dual":
    name = pathlib.Path(args.files[0]).stem.replace("_ring", "").replace("_ref", "")
else:
    name = f"mitdb_{args.label}" if args.label else "mitdb"
out = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "analysis" / f"fiducial_{name}_{VERSION}.txt"
out.write_text(text); print(f"saved {out}")
if args.mode == "dual":
    png = str(out).replace(".txt", ".png"); plot_dual(res, png); print(f"saved {png}")
    if args.zoom:
        z = str(out).replace(".txt", f"_zoom_{args.zoom[0]:g}-{args.zoom[1]:g}s.png")
        plot_zoom(res, args.zoom[0], args.zoom[1], z); print(f"saved {z}")
