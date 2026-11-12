#!/usr/bin/env python3
"""Before and after: tp2.1 (shipped) against the candidate tp3 (tp3_candidate.py).

    ./evaluate_tp3.py mitdb  --dir <main>/data/mitdb <main>/data/mitdb_heldout [--grid]
    ./evaluate_tp3.py own    --captures <main>/captures
    ./evaluate_tp3.py bidmc  --dir <main>/data/bidmc
    ./evaluate_tp3.py incart --dir <main>/data/incartdb          # held-out, once, after the freeze

Both timing points are applied to THE SAME detected beats (tp3 re-times the
detector's beats; detection is not touched), so every difference below is a
difference in where a beat is timed and whether it is flagged.

mitdb / incart: against beat annotations, measured as fiducial.py does:
  sd      robust sd (1.4826 x MAD) of beat time - annotation time, ms, on
          class-N beats whose neighbours are class N, flagged beats left out
  RMSSD error  RMSSD(timing point) - RMSSD(annotations), both on runs of
          consecutive matched class-N beats, both cleaned by the detector's
          rules (pan_tompkins.clean_nn); nan = withheld (under 30 intervals)
  COVERAGE  beats whose interval is used in that RMSSD / all annotated beats.
          It stands next to every RMSSD error.
  NN cov  the pipeline's own coverage, no annotations: accepted intervals /
          all inter-beat intervals (NNSeries.from_beats). This is what decides
          whether the app can show SDNN, LF, HF.
  Se, P+  EC57 at 150 ms on all annotated beats, to confirm that re-timing
          moves no beat out of tolerance.
MIT-BIH: all 48 records are development data from 13 Nov 2026. MLII where the
record has it, 360 -> 256 Hz, 0.5-40 Hz, 60 Hz notch. Paced records separately.
INCART: lead II, 257 -> 256 Hz, 0.5-40 Hz, 50 Hz notch; 75 records from 32
patients, so summaries are given over patients as well as over records. Its
annotations are placed by an algorithm "in the middle of the QRS complex" and
their positions were not corrected by hand (database description), so
annotation RMSSD carries that jitter: errors there are a comparison between
the two timing points, not an absolute accuracy.

own: our recordings. dual03 (finger and chest at once): RR agreement between
the sites and each site's RMSSD with coverage. tb01, tb02 (test board): what
the whole recording can report before and after, and why tp2.1 flags.

bidmc: no beat annotations; flagged share and NN coverage only.

--grid (mitdb only): the tuning table. LAG and R_MIN for the aligned, peak-referenced form, and the three other
combinations of REF and ALIGN at one setting (tp3_candidate.py explains them).

Saves analysis/tp3_<mode>[...].txt.
"""
import argparse, contextlib, io, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["mitdb", "incart", "own", "bidmc"])
ap.add_argument("--dir", nargs="+", default=None)
ap.add_argument("--captures", default="captures")
ap.add_argument("--grid", action="store_true")
ap.add_argument("--cfg", default=None, help="JSON overriding tp3 settings, for development comparisons (not with incart)")
ap.add_argument("--tag", default="", help="suffix for the output file name")
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()

import algorithms as A
from algorithms import frontend
import pan_tompkins as PT
import tp3_candidate as T3

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
FILTERS = ["causal", "zero-phase"]
BEAT = set("NLRejAaJSVEFP/fQ")
AAMI_N = set("NLRej")
PACED = {"102", "104", "107", "217"}
if args.mode == "incart" and not (T3.CONFIG and T3.CONFIG.get("frozen")):
    sys.exit("refusing: tp3_candidate.json is not frozen; INCART is held-out and is run once, after the freeze")
if args.cfg:
    if args.mode == "incart":
        sys.exit("refusing: the held-out run uses tp3_candidate.json as frozen, no overrides")
    T3.DEFAULT.update(json.loads(args.cfg))
    if T3.CONFIG:
        T3.CONFIG["timing"].update(json.loads(args.cfg))
GRID = ([dict(LAG=l, R_MIN=r, ALIGN=True, REF="peak") for l in (10, 14) for r in (0.0, 0.5, 0.7, 0.8, 0.9)]
        + [dict(LAG=10, R_MIN=0.5, ALIGN=a, REF=ref) for ref, a in (("peak", False), ("anchor", True), ("anchor", False))])


def vname(c):
    return f"{c['REF']:6} {'aligned' if c['ALIGN'] else 'unalign'} lag{c['LAG']} r{c['R_MIN']:g}"


# ------------------------------------------------------------------ detector
class Instrumented(PT.PanTompkins):
    """The shipped detector, recording the polarity it had decided for each beat."""
    def __init__(self, fs):
        super().__init__(fs); self.signs = []

    def _finish(self):
        self.signs.append(self._polarity()[0])
        return super()._finish()


def detect(y, skips=None):
    """tp2.1 beats, the polarity sign per beat, and how many the correlation check flagged."""
    pt = Instrumented(FS)
    if skips is None:
        for v in y:
            pt.process(v)
    else:
        for v, s in zip(y, skips):
            if s:
                pt.skip(int(s))
            pt.process(v)
    return pt.beats, pt.signs[:len(pt.beats)], pt.corr_flagged


def rsd(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")


def greedy(ref_t, test_t, tol):
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


def hrv(rr):
    rm, _, _, cov = PT.rmssd_nn(list(rr))
    return (float("nan") if rm is None else rm), cov


# -------------------------------------------------- annotated databases
def ann_record(job):
    path, lead, mains = job
    import wfdb
    rec = os.path.basename(path)
    r = wfdb.rdrecord(path); ann = wfdb.rdann(path, "atr")
    names = list(r.sig_name)
    ch = names.index(lead) if lead in names else 0
    fs0 = float(r.fs)
    x = frontend.resample(r.p_signal[:, ch], fs0)
    sym = np.array(ann.symbol); samp = np.array(ann.sample)
    bidx = np.flatnonzero([s in BEAT for s in sym])
    n_all = len(bidx)
    all_t = samp[bidx] / fs0
    nmask = np.zeros(len(sym), bool)
    for q in range(1, len(bidx) - 1):
        k = bidx[q]
        if sym[k] in AAMI_N and sym[bidx[q - 1]] in AAMI_N and sym[bidx[q + 1]] in AAMI_N:
            nmask[k] = True
    ann_t = samp[nmask] / fs0
    patient = next((c.split()[-1] for c in (r.comments or []) if c.strip().startswith("patient")), rec)
    out = dict(rec=rec, lead=names[ch], patient=patient, n_all=n_all, res={})
    for filt in FILTERS:
        y = frontend.filter_ecg(x, FS, mains, causal=(filt == "causal"))
        beats, signs, ncorr = detect(y)
        det = np.array([b["bp"] for b in beats], dtype=float) / FS
        variants = {"tp2.1": beats}
        if args.grid:
            variants.update({vname(c): T3.retime(y, beats, FS, c) for c in GRID})
        else:
            variants["tp3"] = T3.retime(y, beats, FS)
        pairs = greedy(ann_t, det, 0.15)
        ia = np.array([p[0] for p in pairs], dtype=int); jd = np.array([p[1] for p in pairs], dtype=int)
        row = {}
        for name, bb in variants.items():
            pos = np.array([b["pos"] for b in bb], dtype=float); fl = np.array([b["flagged"] for b in bb], dtype=bool)
            m = dict(flagged=float(fl.mean()) if len(fl) else 0.0, nncov=A.NNSeries.from_beats(bb, FS).coverage,
                     sd=np.nan, err=np.nan, cov=0.0, ann_rmssd=np.nan, n=len(ia))
            ev = greedy(all_t, pos / FS, 0.15)
            m["tp"], m["fp"], m["fn"] = len(ev), len(pos) - len(ev), n_all - len(ev)
            if len(ia) >= 30:
                Aa = ann_t[ia] * 1000; L = pos[jd] / FS * 1000; use = ~fl[jd] & np.isfinite(L)
                rf, ra = [], []
                for q in range(len(ia) - 1):
                    if ia[q + 1] != ia[q] + 1:
                        rf.append(np.nan); ra.append(np.nan); continue
                    ra.append(Aa[q + 1] - Aa[q])
                    rf.append(L[q + 1] - L[q] if use[q] and use[q + 1] else np.nan)
                acc, _ = PT.clean_nn(rf)
                mf, ma = hrv(rf)[0], hrv(ra)[0]
                m.update(sd=rsd((L - Aa)[use]), err=mf - ma, cov=int(sum(acc)) / max(1, n_all - 1), ann_rmssd=ma)
            row[name] = m
        und = sum(1 for b, s in zip(beats, signs) if b["flagged"] and s == 0)
        out["res"][filt] = dict(m=row, beats=len(beats), undecided=und, corr=ncorr)
    return out


def mm(v, f="{:+.2f}"):
    v = np.array(v, float); v = v[np.isfinite(v)]
    return (f.format(np.median(v)) + " [" + f.format(v.min()) + ", " + f.format(v.max()) + "]") if len(v) else "n/a"


def summary_line(name, rows, filt):
    ms = [r["res"][filt]["m"][name] for r in rows]
    tp = sum(m["tp"] for m in ms); fp = sum(m["fp"] for m in ms); fn = sum(m["fn"] for m in ms)
    err = np.array([m["err"] for m in ms]); cov = np.array([m["cov"] for m in ms]); nn = np.array([m["nncov"] for m in ms])
    ae = np.abs(err[np.isfinite(err)])
    return (f"{name:24} {mm([m['sd'] for m in ms], '{:.2f}'):>21} {mm(err):>24} {ae.max() if len(ae) else float('nan'):6.2f} "
            f"{ae.mean() if len(ae) else float('nan'):6.2f} {int((ae > 1).sum()):4d} {int(np.isnan(err).sum()):4d} {mm(100 * cov, '{:.0f}'):>14} {int((cov < 0.2).sum()):5d} {mm(100 * nn, '{:.0f}'):>14} "
            f"{int((nn < 0.5).sum()):5d} | {100*tp/(tp+fn):6.2f} {100*tp/(tp+fp):6.2f}")


SUM_HEAD = (f"{'timing point':24} {'sd vs annotation, ms':>21} {'RMSSD error, ms':>24} {'max|e|':>6} {'mean|e|':>6} {'>1ms':>4} {'w/h':>4} {'coverage %':>14} "
            f"{'<20%':>5} {'NN cov %':>14} {'<50%':>5} | {'Se':>6} {'P+':>6}")
SUM_NOTE = ("median [min, max] over records. max|e|, mean|e|, >1ms = largest and mean absolute RMSSD error and the number of records over "
            "1 ms, among records with a value. w/h = records whose RMSSD is withheld (they have no error); <20% = records with "
            "coverage under 20%; <50% = records whose pipeline NN coverage is under 50%.")


def report_ann(rows, groups, per_patient=False):
    names = list(rows[0]["res"]["causal"]["m"])
    for filt in FILTERS:
        for label, keep in groups:
            rr = [r for r in rows if keep(r)]
            if not rr:
                continue
            print(f"=== {filt} filter, {label}: {len(rr)} records ===")
            print(SUM_HEAD)
            for n in names:
                print(summary_line(n, rr, filt))
            if per_patient:
                print(f"over the {len(set(r['patient'] for r in rr))} patients (each patient's records averaged first), median [min, max]:")
                for n in names:
                    pp = {}
                    for r in rr:
                        pp.setdefault(r["patient"], []).append(r["res"][filt]["m"][n])
                    err = [np.nanmean([m["err"] for m in v]) if np.isfinite([m["err"] for m in v]).any() else np.nan for v in pp.values()]
                    cov = [np.mean([m["cov"] for m in v]) for v in pp.values()]
                    nn = [np.mean([m["nncov"] for m in v]) for v in pp.values()]
                    print(f"{n:24} RMSSD error {mm(err):>24}, patients with none {int(np.isnan(err).sum())}; coverage % "
                          f"{mm(100 * np.array(cov), '{:.0f}'):>14}; NN cov % {mm(100 * np.array(nn), '{:.0f}'):>14}, under 50% in "
                          f"{int((np.array(nn) < 0.5).sum())}")
            print()
    print(SUM_NOTE + "\n")
    if args.grid:
        return
    for filt in FILTERS:
        print(f"per record, {filt}: sd ms / RMSSD error ms / coverage %  |  NN cov % and flagged %, tp2.1 -> tp3  |  why tp2.1 flagged")
        print(f"{'rec':>5} {'pat':>4} {'lead':>5} {'N beats':>7} {'ann RMSSD':>9} | {'tp2.1':^21} | {'tp3':^21} | {'NN cov':^11} {'flagged':^13} | "
              f"{'undecided':>9} {'check':>6}")
        for r in rows:
            f = r["res"][filt]; a, b = f["m"]["tp2.1"], f["m"]["tp3"]
            cell = lambda m: f"{m['sd']:5.2f} {m['err']:+7.2f} {100*m['cov']:4.0f}%"
            print(f"{r['rec']:>5} {r['patient'] if per_patient else '':>4} {r['lead']:>5} {a['n']:7d} {a['ann_rmssd']:7.1f}ms | "
                  f"{cell(a):^21} | {cell(b):^21} | {100*a['nncov']:4.0f} ->{100*b['nncov']:4.0f} {100*a['flagged']:5.1f} ->{100*b['flagged']:5.1f} | "
                  f"{100*f['undecided']/max(1, f['beats']):8.1f}% {100*f['corr']/max(1, f['beats']):5.1f}%")
        print()
    print("'undecided' = share of beats tp2.1 flagged because the median beat's polarity was not decided; 'check' = share its "
          "correlation check flagged.")


# ------------------------------------------------------------ own recordings
def load_capture(path, skip_s=0.0):
    """(values, skip_before) of a capture CSV by sample index: duplicate rows
    dropped, lost indices reported as skips."""
    import pandas as pd
    df = pd.read_csv(path, on_bad_lines="skip", low_memory=False)
    n_rows = len(df)
    df = df.assign(index=pd.to_numeric(df["index"], errors="coerce"), value=pd.to_numeric(df["value"], errors="coerce")).dropna(subset=["index", "value"])
    idx = df["index"].to_numpy().astype(np.int64); val = df["value"].to_numpy().astype(float)
    raw = np.empty(n_rows)          # only its length is used below
    _, first = np.unique(idx, return_index=True)
    first.sort(); idx, val = idx[first], val[first]
    order = np.argsort(idx, kind="stable"); idx, val = idx[order], val[order]
    s = int(skip_s * FS)
    idx, val = idx[s:], val[s:]
    skips = np.concatenate([[0], np.diff(idx) - 1])
    return val, skips, len(raw) - len(first)


def by_index(y, skips):
    """Filtered samples laid out by sample index, NaN where samples were lost."""
    out = []
    for v, s in zip(y, skips):
        if s:
            out.extend([np.nan] * int(s))
        out.append(v)
    return np.array(out)


def own_single(name, path):
    val, skips, dup = load_capture(path)
    print(f"=== {name}: {path} ===")
    print(f"{len(val)} samples ({len(val)/FS:.1f} s), {int(skips.sum())} lost in {int((skips > 0).sum())} gaps, {dup} duplicate rows dropped")
    for filt in FILTERS:
        y = frontend.filter_ecg(val, FS, 50.0, causal=(filt == "causal"), harmonic=True)
        beats, signs, ncorr = detect(y, skips)
        yi = by_index(y, skips)
        und = sum(1 for b, s in zip(beats, signs) if b["flagged"] and s == 0)
        oth = sum(b["flagged"] for b in beats) - und - ncorr
        print(f"{filt}: {len(beats)} beats; tp2.1 flagged {sum(b['flagged'] for b in beats)} = {und} polarity undecided + "
              f"{ncorr} correlation check + {oth} other (window edge or gap)")
        for label, bb in (("tp2.1", beats), ("tp3", T3.retime(yi, beats, FS))):
            nn = A.NNSeries.from_beats(bb, FS)
            h = A.hrv(nn)
            shown = "  ".join(f"{k} {h[k].value:.1f}" if h[k].ok else f"{k} -" for k in ("rmssd", "sdnn", "pnn50", "sd1", "sd2", "lf", "hf", "lf_hf", "dfa_alpha1"))
            print(f"  {label:6} flagged {100*np.mean([b['flagged'] for b in bb]):5.1f}%  NN coverage {100*nn.coverage:5.1f}%  valid {nn.valid_s:6.1f} s | {shown}")
    print()


def own_dual(chest_p, finger_p):
    print(f"=== dual03, finger against chest at the same time ===\nchest  {chest_p}\nfinger {finger_p}")
    print("skip 10 s, longest unbroken run of each (as fiducial.py dual). RR LoA = finger - chest RR on consecutive matched beats with")
    print("neither beat flagged at either site; RMSSD per site on its own cleaned NN series, cov = coverage.\n")

    def load(path):
        raw = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8", invalid_raise=False)
        idx = raw["index"].astype(np.int64); val = raw["value"].astype(float); host = raw["host_time"].astype(float)
        s = int(10.0 * FS); idx, val, host = idx[s:], val[s:], host[s:]
        br = np.flatnonzero(np.diff(idx) != 1) + 1
        keep = max(np.split(np.arange(len(idx)), br), key=len)
        return val[keep], float(host[keep][0])
    (cx, ch0), (fx, fh0) = load(chest_p), load(finger_p)
    for filt in FILTERS:
        site = {}
        for s, x, h0 in (("chest", cx, ch0), ("finger", fx, fh0)):
            y = frontend.filter_ecg(x, FS, 50.0, causal=(filt == "causal"), harmonic=True)
            beats, _, _ = detect(y)
            site[s] = dict(h0=h0, det=np.array([b["bp"] for b in beats], float), v={"tp2.1": beats, "tp3": T3.retime(y, beats, FS)})
        tc = site["chest"]["h0"] + site["chest"]["det"] / FS; tf = site["finger"]["h0"] + site["finger"]["det"] / FS
        off = 0.0
        for _ in range(4):
            j = np.clip(np.searchsorted(tc, tf - off), 1, len(tc) - 1)
            near = np.where(np.abs(tc[j] - (tf - off)) < np.abs(tc[j - 1] - (tf - off)), j, j - 1)
            dd = (tf - off) - tc[near]; off += float(np.median(dd[np.abs(dd) < 0.15]))
        pairs = greedy(tc, tf - off, 0.15)
        ic = np.array([p[0] for p in pairs]); jf = np.array([p[1] for p in pairs])
        cons = np.flatnonzero((np.diff(ic) == 1) & (np.diff(jf) == 1))
        print(f"{filt} filter: chest {len(tc)} beats, finger {len(tf)}, matched {len(pairs)}")
        print(f"  {'timing':6} {'dt sd ms':>8} {'flag pairs':>10} | {'RR LoA ms':>14} {'n':>4} | {'RMSSD chest':>11} {'cov':>4} {'finger':>7} {'cov':>4}")
        for name in ("tp2.1", "tp3"):
            pc = np.array([b["pos"] for b in site["chest"]["v"][name]]) / FS * 1000; fc = np.array([b["flagged"] for b in site["chest"]["v"][name]])
            pf = np.array([b["pos"] for b in site["finger"]["v"][name]]) / FS * 1000; ff = np.array([b["flagged"] for b in site["finger"]["v"][name]])
            okp = ~(fc[ic] | ff[jf]); dt = (pf[jf] - pc[ic])[okp]
            bad = fc[ic[cons]] | fc[ic[cons + 1]] | ff[jf[cons]] | ff[jf[cons + 1]]
            drr = ((pf[jf[cons + 1]] - pf[jf[cons]]) - (pc[ic[cons + 1]] - pc[ic[cons]]))[~bad]
            bias, sd = float(np.mean(drr)), float(np.std(drr, ddof=1))

            def ser(p, f):
                rr = np.diff(p); rr[f[:-1] | f[1:]] = np.nan; return hrv(rr)
            (rc, cc), (rf_, cf) = ser(pc, fc), ser(pf, ff)
            print(f"  {name:6} {np.std(dt - np.median(dt), ddof=1):8.2f} {int((~okp).sum()):10d} | {bias-1.96*sd:+6.1f}..{bias+1.96*sd:+5.1f} {len(drr):4d} | "
                  f"{rc:9.1f}ms {100*cc:3.0f}% {rf_:5.1f}ms {100*cf:3.0f}%")
    print()


# --------------------------------------------------------------------- bidmc
def bidmc_record(rec):
    import wfdb
    r = wfdb.rdrecord(f"{args.dir[0]}/bidmc{rec}")
    names = [n.strip(", ") for n in r.sig_name]
    x = r.p_signal[:, names.index("II")].astype(float)
    if np.isnan(x).any():
        k = np.arange(len(x)); ok = np.isfinite(x); x = np.interp(k, k[ok], x[ok])
    x = frontend.resample(x, float(r.fs))
    out = {"rec": rec}
    for filt in FILTERS:
        y = frontend.filter_ecg(x, FS, 60.0, causal=(filt == "causal"))
        beats, signs, ncorr = detect(y)
        b3 = T3.retime(y, beats, FS)
        out[filt] = dict(beats=len(beats), f21=np.mean([b["flagged"] for b in beats]), f3=np.mean([b["flagged"] for b in b3]),
                         c21=A.NNSeries.from_beats(beats, FS).coverage, c3=A.NNSeries.from_beats(b3, FS).coverage,
                         und=sum(1 for b, s in zip(beats, signs) if b["flagged"] and s == 0) / max(1, len(beats)))
    return out


# ---------------------------------------------------------------------- main
def header():
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "tp3_candidate.py", "tp3_candidate.json", "evaluate_tp3.py",
                            "pan_tompkins.py", "tp2_config.json", "algorithms"], capture_output=True, text=True).stdout.strip()
    print(f"# ./evaluate_tp3.py {' '.join(sys.argv[1:])}")
    if args.cfg:
        print(f"# DEVELOPMENT COMPARISON with overrides {args.cfg}: tp3 settings in effect {json.dumps(T3.DEFAULT if not T3.CONFIG else T3.CONFIG['timing'])}")
    print(f"# commit {commit}{' + uncommitted changes' if dirty else ''}; detector {PT.CONFIG['version']} (tp2_config.json, unchanged)")
    if T3.CONFIG:
        print(f"# tp3 candidate: {json.dumps(T3.CONFIG['timing'])}, frozen: {T3.CONFIG.get('frozen')}")
    else:
        print(f"# tp3 candidate: no tp3_candidate.json yet; defaults {json.dumps(T3.DEFAULT)}")
    print(f"# tp3 uses tp2.1's window ({PT.CONFIG['detector']['R_BEFORE_S']} s before to {PT.CONFIG['detector']['R_AFTER_S']} s after the 5-15 Hz peak) "
          f"and template depth (POL_KEEP {PT.CONFIG['detector']['POL_KEEP']}, POL_MIN {PT.CONFIG['detector']['POL_MIN']})\n")


def main():
    import multiprocessing as mp
    buf = io.StringIO()
    if args.mode in ("mitdb", "incart"):
        dirs = args.dir or (["data/mitdb", "data/mitdb_heldout"] if args.mode == "mitdb" else ["data/incartdb"])
        paths = sorted(str(p.with_suffix("")) for d in dirs for p in pathlib.Path(d).glob("*.hea"))
        lead, mains = ("MLII", 60.0) if args.mode == "mitdb" else ("II", 50.0)
        with mp.Pool(args.jobs) as pool:
            rows = pool.map(ann_record, [(p, lead, mains) for p in paths])
        with contextlib.redirect_stdout(buf):
            header()
            if args.mode == "mitdb":
                print(f"MIT-BIH Arrhythmia, {len(rows)} records, all development data. Lead MLII where present (else channel 0).\n")
                report_ann(rows, [("44 non-paced records", lambda r: r["rec"] not in PACED),
                                  ("4 paced records (102 104 107 217)", lambda r: r["rec"] in PACED)])
            else:
                print(f"St Petersburg INCART 12-lead Arrhythmia Database, {len(rows)} records from "
                      f"{len(set(r['patient'] for r in rows))} patients. HELD-OUT: run once with tp3_candidate.json frozen. Lead II.\n")
                report_ann(rows, [("all records", lambda r: True)], per_patient=True)
        name = f"tp3_{args.mode}{'48_dev' if args.mode == 'mitdb' else '_heldout'}{'_grid' if args.grid else ''}.txt"
    elif args.mode == "own":
        cap = pathlib.Path(args.captures)
        with contextlib.redirect_stdout(buf):
            header()
            print("Our own recordings. 50 Hz notch with its 2nd harmonic, as agreement.py.\n")
            own_dual(str(cap / "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv"),
                     str(cap / "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv"))
            own_single("tb01", str(cap / "20261027_173714_testboard01.csv"))
            own_single("tb02", str(cap / "20261027_174352_testboard02.csv"))
        name = "tp3_own_recordings.txt"
    else:
        recs = sorted(p.stem[5:] for p in pathlib.Path(args.dir[0]).glob("bidmc??.hea"))
        with mp.Pool(args.jobs) as pool:
            rows = pool.map(bidmc_record, recs)
        with contextlib.redirect_stdout(buf):
            header()
            print(f"BIDMC, all {len(rows)} recordings (46 subjects), lead II. No beat annotations: flagged share and pipeline NN coverage only.\n")
            for filt in FILTERS:
                c21 = np.array([r[filt]["c21"] for r in rows]); c3 = np.array([r[filt]["c3"] for r in rows])
                print(f"=== {filt} filter ===")
                print(f"NN coverage, median [min, max]: tp2.1 {mm(100*c21, '{:.0f}')}%, tp3 {mm(100*c3, '{:.0f}')}%; recordings under 50%: "
                      f"tp2.1 {int((c21 < 0.5).sum())}, tp3 {int((c3 < 0.5).sum())}; under 95% (no LF/HF): tp2.1 {int((c21 < 0.95).sum())}, tp3 {int((c3 < 0.95).sum())}")
                print(f"{'rec':>4} {'beats':>6} | {'flagged % 2.1 -> 3':>20} | {'NN cov % 2.1 -> 3':>19} | {'tp2.1 undecided %':>17}")
                for r in rows:
                    f = r[filt]
                    print(f"{r['rec']:>4} {f['beats']:6d} | {100*f['f21']:8.1f} -> {100*f['f3']:5.1f}   | {100*f['c21']:7.0f} -> {100*f['c3']:4.0f}    | {100*f['und']:10.1f}")
                print()
        name = "tp3_bidmc_coverage.txt"
    text = buf.getvalue(); print(text, end="")
    name = name.replace(".txt", f"{args.tag}.txt")
    (HERE / "analysis" / name).write_text(text); print(f"saved {HERE / 'analysis' / name}")


if __name__ == "__main__":
    main()
