#!/usr/bin/env python3
"""Check the HRV functions in algorithms/ against neurokit2, on MIT-BIH.

    ./validate_hrv_neurokit.py --set dev     --dir <main checkout>/data/mitdb
    ./validate_hrv_neurokit.py --set heldout --dir <main checkout>/data/mitdb_heldout

WHAT THIS TESTS. Both libraries are given the SAME NN series, so this is a
check of arithmetic and definitions: does our RMSSD, LF/HF, alpha1 ... come out
as an independent implementation's does on real beat series with real holes.
It says nothing about whether the beats are in the right place (fiducial.py and
the EC57 benchmark do that) or whether HRV from an arrhythmia database means
anything physiologically.

THE NN SERIES. Each record's MLII lead (channel 0 where there is none),
resampled to 256 Hz, zero-phase 0.5-40 Hz with a 60 Hz notch as in
benchmark_mitdb.py, through pan_tompkins.py with tp2_config.json as frozen
(tp2.1). Intervals are cleaned by the detector's own rules (NNSeries.from_beats)
and cut into non-overlapping windows. neurokit2 gets the accepted intervals of
a window with their beat times ({"RRI", "RRI_Time"}), which is how it is told
where the holes are.

TWO TABLES per window length.
  A, as shipped: our value where the minimum window lets us report one.
     COVERAGE = windows reported / all windows, next to every difference.
  B, gates off: every window where both libraries produce a number, to compare
     the arithmetic on as many windows as possible. Not something we report.
Windows are split into "no holes" (every interval accepted) and "holes".
neurokit2 handles holes for RMSSD, pNN50, SD1, SD2 (successive pairs only) and
Lomb-Scargle; for DFA and SampEn it joins the pieces end to end, which we do
not, so on windows with holes a difference there is expected and is not an
error of either.

References used for each measure:
  RMSSD, SDNN, SD1, SD2  nk.hrv_time / nk.hrv_nonlinear, as they come
  pNN50      nk.hrv_time; "same denominator" rescales nk's NN50/(differences+1)
             to our NN50/differences
  LF, HF     nk.hrv_frequency(psd_method="lomb", normalize=False,
             interpolation_rate=None), times 2T/N to turn its integral of the
             raw periodogram into ms^2 (T = span, N = intervals)
  LF/HF      the same call's HRV_LFHF, unscaled
  "on nk's grid"  OUR periodogram, integrated the way neurokit2 integrates its
             own: on astropy's frequency grid, which starts at neurokit2's
             minimum frequency 4 x median(NN) / N and has step 1/(5T), over the
             points inside each band. This row compares the periodograms. The
             rows above also include the difference between the two grids: ours
             has step 1/(8T) and includes both band edges; neurokit2's starts
             ABOVE 0.04 Hz when a window holds fewer than about 100 x median NN
             (s) intervals, so its LF then covers only part of the band.
  alpha1     "matched": nk.fractal_dfa(scale=4..16, overlap=False), our box
             sizes and layout. "default": nk.hrv_nonlinear's HRV_DFA_alpha1,
             which uses box sizes 4-11 and half-overlapping boxes: a different
             definition, shown so the size of that difference is on record.
  SampEn     nk.hrv_nonlinear's HRV_SampEn (m=2, r=0.2 sd)

Saves analysis/hrv_vs_neurokit_mitdb_<set>.txt.
"""
import argparse, contextlib, copy, io, json, os, pathlib, subprocess, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs under python -I
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--set", choices=["dev", "heldout"], required=True)
ap.add_argument("--dir", default=None, help="default data/mitdb (dev) or data/mitdb_heldout (heldout)")
ap.add_argument("--records", nargs="*", help="default: every .hea in --dir")
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()

import algorithms as A
from algorithms import core, frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
DIR = args.dir or ("data/mitdb" if args.set == "dev" else "data/mitdb_heldout")
if args.set == "heldout" and A.CONFIG["frozen"] is None:
    sys.exit("refusing: algorithms/config.json is not frozen ('frozen' is null); "
             "freeze and commit it before any held-out run")
PACED = {"102", "104", "107", "217"}
WINDOWS = A.CONFIG["mitdb"]["window_s"]
MEASURES = ["rmssd", "sdnn", "pnn50", "lf", "hf", "lf_hf", "sd1", "sd2", "dfa_alpha1", "sampen"]
LABEL = {"rmssd": "RMSSD ms", "sdnn": "SDNN ms", "pnn50": "pNN50 %", "lf": "LF ms^2", "hf": "HF ms^2",
         "lf_hf": "LF/HF", "sd1": "SD1 ms", "sd2": "SD2 ms", "dfa_alpha1": "DFA alpha1", "sampen": "SampEn"}
# (our measure, reference key, label of the reference)
COMPARE = [("rmssd", "rmssd", "nk"), ("sdnn", "sdnn", "nk"), ("pnn50", "pnn50", "nk"),
           ("pnn50", "pnn50_same", "nk, same denominator"), ("lf", "lf", "nk x 2T/N"), ("hf", "hf", "nk x 2T/N"),
           ("lf_hf", "lf_hf", "nk"),
           ("lf@grid", "lf", "nk x 2T/N, nk's grid"), ("hf@grid", "hf", "nk x 2T/N, nk's grid"),
           ("lf_hf@grid", "lf_hf", "nk, nk's grid"),
           ("sd1", "sd1", "nk"), ("sd2", "sd2", "nk"),
           ("dfa_alpha1", "dfa_matched", "nk matched"), ("dfa_alpha1", "dfa_default", "nk default 4-11"),
           ("sampen", "sampen", "nk")]


def neurokit(nn, n_diffs):
    """neurokit2's values for one window, NaN where it gives none."""
    import neurokit2 as nk
    out = {k: np.nan for _, k, _ in COMPARE}
    rri, t = nn.values, nn.times
    if len(rri) < 4:
        return out
    d = {"RRI": rri, "RRI_Time": t}

    def grab(fn, pairs, **kw):
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                df = fn(d, **kw)
            for key, col, scale in pairs:
                v = float(df[col].iloc[0]) * scale
                out[key] = v if np.isfinite(v) else np.nan
        except Exception:
            pass

    grab(nk.hrv_time, [("rmssd", "HRV_RMSSD", 1.0), ("sdnn", "HRV_SDNN", 1.0), ("pnn50", "HRV_pNN50", 1.0)])
    if n_diffs:
        out["pnn50_same"] = out["pnn50"] * (n_diffs + 1) / n_diffs
    k = 2.0 * float(t[-1] - t[0]) / len(rri)
    grab(nk.hrv_frequency, [("lf", "HRV_LF", k), ("hf", "HRV_HF", k), ("lf_hf", "HRV_LFHF", 1.0)],
         psd_method="lomb", normalize=False, interpolation_rate=None)
    grab(nk.hrv_nonlinear, [("sd1", "HRV_SD1", 1.0), ("sd2", "HRV_SD2", 1.0),
                            ("dfa_default", "HRV_DFA_alpha1", 1.0), ("sampen", "HRV_SampEn", 1.0)])
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            v, _ = nk.fractal_dfa(rri, scale=np.arange(4, 17), overlap=False)
        out["dfa_matched"] = float(v) if np.isfinite(v) else np.nan
    except Exception:
        pass
    return out


def ours_on_nk_grid(nn):
    """Our Lomb-Scargle periodogram integrated on neurokit2's frequency grid."""
    import astropy.timeseries as ats
    from algorithms.hrv_freq import lomb_scargle, BANDS
    t, v = nn.times, nn.values
    out = {"lf@grid": None, "hf@grid": None, "lf_hf@grid": None}
    if len(v) < 4:
        return out
    try:
        fmin = (2 * np.median(np.diff(t))) / (len(v) / 2)          # neurokit2 signal_psd, t given
        y = v - v.mean()
        f = np.asarray(ats.LombScargle(t, y).autofrequency(minimum_frequency=fmin))
        p = lomb_scargle(t, y, f) * 2.0 * float(t[-1] - t[0]) / len(v)
        for k in ("lf", "hf"):
            m = (f >= BANDS[k][0]) & (f < BANDS[k][1])
            val = float(np.trapezoid(p[m], f[m]))
            out[k + "@grid"] = val if val > 0 else None
        if out["lf@grid"] and out["hf@grid"]:
            out["lf_hf@grid"] = out["lf@grid"] / out["hf@grid"]
    except Exception:
        pass
    return out


def ours_ungated(nn):
    """Our values with every minimum set to nothing (table B only)."""
    saved = copy.deepcopy(core.MIN_WINDOW)
    try:
        for req in core.MIN_WINDOW.values():
            for k in req:
                req[k] = 0
        core.MIN_WINDOW["rmssd"]["pairs"] = core.MIN_WINDOW["sd1"]["pairs"] = 2
        core.MIN_WINDOW["pnn50"]["pairs"] = core.MIN_WINDOW["sd2"]["pairs"] = 2
        core.MIN_WINDOW["dfa_alpha1"]["nn_in_runs"] = 17
        core.MIN_WINDOW["sampen"]["templates"] = 2
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return {k: r.value for k, r in A.hrv(nn).items()}
            except Exception:
                return {}
    finally:
        core.MIN_WINDOW.clear(); core.MIN_WINDOW.update(saved)


def one_record(rec):
    import wfdb
    r = wfdb.rdrecord(f"{DIR}/{rec}")
    names = list(r.sig_name)
    ch = names.index("MLII") if "MLII" in names else 0
    x = frontend.resample(r.p_signal[:, ch], float(r.fs))
    y = frontend.filter_ecg(x, frontend.FS, 60.0, causal=False)
    beats = frontend.detect(y, frontend.FS)
    nn = A.NNSeries.from_beats(beats, frontend.FS)
    dur = len(x) / frontend.FS
    rows = []
    for W in WINDOWS:
        for i in range(int(dur // W)):
            w = nn.window(i * W, (i + 1) * W)
            res = A.hrv(w)
            a, _ = w.pairs()
            grid = ours_on_nk_grid(w)
            ours = {k: res[k].value for k in MEASURES}
            raw = ours_ungated(w)
            for k, v in grid.items():            # shown wherever the measure itself is
                base = k.split("@")[0]
                ours[k] = v if ours[base] is not None else None
                raw[k] = v if raw.get(base) is not None else None
            rows.append(dict(rec=rec, W=W, i=i, coverage=w.coverage, valid_s=w.valid_s, n=w.n_accepted,
                             holes=w.n_accepted < w.n_intervals, ours=ours,
                             why={k: res[k].withheld for k in MEASURES},
                             raw=raw, nk=neurokit(w, len(a))))
    return dict(rec=rec, lead=names[ch], beats=len(beats),
                flagged=sum(b["flagged"] for b in beats), searchback=sum(b["kind"] != "primary" for b in beats),
                coverage=nn.coverage, rows=rows)


def diff_stats(pairs):
    """n, median difference, largest |difference|, median and largest relative |difference| (%)."""
    if not pairs:
        return f"{0:5d} {'-':>11} {'-':>11} {'-':>9} {'-':>9}"
    o = np.array([p[0] for p in pairs]); n = np.array([p[1] for p in pairs])
    d = o - n
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = 100 * np.abs(d) / np.abs(n)
    rel = rel[np.isfinite(rel)]
    rm = f"{np.median(rel):9.2g} {rel.max():9.2g}" if len(rel) else f"{'-':>9} {'-':>9}"
    return f"{len(d):5d} {np.median(d):+11.3g} {np.abs(d).max():11.3g} {rm}"


def tables(recs, title):
    print(f"################ {title}: {len(recs)} records ################\n")
    for W in WINDOWS:
        rows = [w for r in recs for w in r["rows"] if w["W"] == W]
        n_all = len(rows); n_holes = sum(w["holes"] for w in rows)
        print(f"=== {W:g} s windows: {n_all} windows, {n_all - n_holes} without holes, {n_holes} with ===")
        print("how many windows each measure is reported in (the minimum window decides):")
        print("  " + "  ".join(f"{LABEL[m].split()[0]} {sum(w['ours'][m] is not None for w in rows)}" for m in MEASURES))
        for tab, key, note in (("A", "ours", "as shipped: our minimum windows applied"),
                               ("B", "raw", "gates off: arithmetic only, not reported values")):
            print(f"\n  table {tab} ({note}); difference = ours - reference")
            print(f"  {'measure':11} {'reference':22} {'reported':>14} | {'no holes: n':>11} {'median':>11} {'max |d|':>11} "
                  f"{'med rel%':>9} {'max rel%':>9} | {'holes: n':>8} {'median':>11} {'max |d|':>11} {'med rel%':>9} {'max rel%':>9}")
            for m, ref, lab in COMPARE:
                have = [w for w in rows if w[key].get(m) is not None]
                both = [w for w in have if np.isfinite(w["nk"][ref])]
                clean = [(w[key][m], w["nk"][ref]) for w in both if not w["holes"]]
                holed = [(w[key][m], w["nk"][ref]) for w in both if w["holes"]]
                cov = f"{len(have):4d}/{n_all:<4d} {100 * len(have) / max(1, n_all):3.0f}%"
                print(f"  {LABEL[m.split('@')[0]]:11} {lab:22} {cov:>14} | {diff_stats(clean):>55} | {diff_stats(holed):>52}")
        print()


def main():
    recs = args.records or sorted(p.stem for p in pathlib.Path(DIR).glob("*.hea"))
    if not recs:
        sys.exit(f"no records in {DIR}")
    import multiprocessing as mp
    with mp.Pool(min(args.jobs, len(recs))) as pool:
        out = pool.map(one_record, recs)
    import neurokit2, astropy, scipy
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "algorithms", "pan_tompkins.py",
                            "tp2_config.json", "validate_hrv_neurokit.py"], capture_output=True, text=True).stdout.strip()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"# ./validate_hrv_neurokit.py {' '.join(sys.argv[1:])}")
        print(f"# commit {commit}{' + uncommitted changes' if dirty else ''}; algorithms {A.VERSION}, "
              f"frozen: {A.CONFIG['frozen']}; detector {core.PT.CONFIG['version']} (tp2_config.json)")
        print(f"# neurokit2 {neurokit2.__version__}, astropy {astropy.__version__}, scipy {scipy.__version__}, numpy {np.__version__}")
        print(f"# hrv settings: {json.dumps({k: v for k, v in A.CONFIG['hrv'].items() if k != 'min_window'})}")
        print(f"# minimum windows: {json.dumps(A.CONFIG['hrv']['min_window'])}")
        print(f"# MIT-BIH {args.set} set, {len(recs)} records from {DIR}: {' '.join(recs)}")
        print("# front end: MLII (channel 0 where absent), resampled to 256 Hz, zero-phase 0.5-40 Hz, 60 Hz notch;")
        print(f"# beats: tp2.1; windows: non-overlapping {', '.join(f'{w:g} s' for w in WINDOWS)}\n")
        w0 = WINDOWS[0]
        print(f"per record: NN coverage = accepted intervals / all inter-beat intervals; then the number of "
              f"{w0:g} s windows in which each measure is reported")
        print(f"{'rec':>4} {'lead':>5} {'beats':>6} {'flagged':>8} {'srch-back':>9} {'NN cov':>7} {'windows':>8} | "
              + " ".join(f"{LABEL[m].split()[0]:>6}" for m in MEASURES))
        for r in out:
            rows = [w for w in r["rows"] if w["W"] == w0]
            print(f"{r['rec']:>4} {r['lead']:>5} {r['beats']:6d} {100*r['flagged']/max(1, r['beats']):7.1f}% "
                  f"{100*r['searchback']/max(1, r['beats']):8.1f}% {100*r['coverage']:6.1f}% {len(rows):8d} | "
                  + " ".join(f"{sum(w['ours'][m] is not None for w in rows):6d}" for m in MEASURES))
        print()
        if args.set == "heldout":
            tables([r for r in out if r["rec"] not in PACED], "held-out, non-paced")
            paced = [r for r in out if r["rec"] in PACED]
            if paced:
                tables(paced, "held-out, paced (102 104 107 217), reported separately")
        else:
            tables(out, "development set")
        why = {}
        for r in out:
            for w in r["rows"]:
                if w["W"] == w0:
                    for m in MEASURES:
                        if w["ours"][m] is None:
                            k = (m, "".join(c for c in w["why"][m].split(",")[-1] if not c.isdigit()).strip())
                            why[k] = why.get(k, 0) + 1
        print(f"why values were withheld, {w0:g} s windows (digits removed to group the reasons):")
        for (m, reason), c in sorted(why.items(), key=lambda kv: (MEASURES.index(kv[0][0]), -kv[1])):
            print(f"  {LABEL[m]:11} {c:4d}  {reason}")
    text = buf.getvalue(); print(text, end="")
    path = HERE / "analysis" / f"hrv_vs_neurokit_mitdb_{args.set}.txt"
    path.write_text(text); print(f"saved {path}")


if __name__ == "__main__":
    main()
