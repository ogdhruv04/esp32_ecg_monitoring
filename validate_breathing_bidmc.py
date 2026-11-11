#!/usr/bin/env python3
"""ECG-derived breathing rate against the annotated breaths in BIDMC.

    ./validate_breathing_bidmc.py --set dev     --dir <main checkout>/data/bidmc [--tune]
    ./validate_breathing_bidmc.py --set heldout --dir <main checkout>/data/bidmc

DATA. BIDMC PPG and Respiration Dataset (Pimentel et al. 2017, PhysioNet,
ODC-By 1.0): 53 eight-minute recordings from intensive-care patients, lead II
ECG at 125 Hz, every breath marked by two annotators on the impedance signal.
The 53 recordings come from 46 subjects, so the split in algorithms/config.json
is by SUBJECT: 23 development subjects (26 recordings), 23 held-out (27).
Parameters are tuned on the development subjects only. The held-out subjects
are refused until config.json carries a freeze date, and are run once.

REFERENCE, as Pimentel et al.: 32 s windows starting every 3 s; per annotator
the rate is 60 / mean time between consecutive breaths in the window; a window
counts only when the two annotators agree within 2 breaths/min, and the
reference is their mean.

ESTIMATE. Lead II resampled to 256 Hz, the monitoring filter (0.5-40 Hz, 60 Hz
notch) both zero-phase and causal (the phone's), tp2.1 beats, then
algorithms.breathing_rate on the same windows: RSA, R amplitude, and fused.

WHAT IS REPORTED, per method and filter:
  coverage   windows with a reported rate / windows with a valid reference.
             A withheld window is not an error and not a success; it is here.
  MAE        mean |estimate - reference|, breaths/min, over reported windows:
             pooled, and per subject (median and quartiles over subjects, which
             is what counts as independent; windows overlap by 29 s).
  bias, LoA  mean and +-1.96 sd of estimate - reference over pooled windows.
             The windows are not independent, so the limits are descriptive.
"ungated" rows switch the peak-share gate off (peak_share_min = 0) to show
what the gate buys and costs. All other minimums stay on.

--tune (dev only) evaluates a grid of settings and saves the table; choosing
from it is done by hand and written into config.json before the freeze.

Saves analysis/breathing_bidmc_<set>.txt (or ..._dev_tuning.txt).
"""
import argparse, contextlib, io, itertools, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs under python -I
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--set", choices=["dev", "heldout"], required=True)
ap.add_argument("--dir", default="data/bidmc")
ap.add_argument("--tune", action="store_true", help="dev only: evaluate the tuning grid")
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()

import algorithms as A
from algorithms import core, frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
B = A.CONFIG["bidmc"]
if args.set == "heldout" and (A.CONFIG["frozen"] is None or args.tune):
    sys.exit("refusing: the held-out subjects are evaluated once, with algorithms/config.json frozen, and never tuned on")
SUBJECT = {rec: sid for sid, recs in B[args.set].items() for rec in recs}
W, STEP, AGREE = B["window_s"], B["step_s"], B["ref_agree_bpm"]
FILTERS = ["causal", "zero-phase"]
METHODS = ["rsa", "ramp", "fused"]
AMP = {"baseline": ("baseline", False), "peak_to_peak": ("peak_to_peak", False),
       "peak_to_peak+flagged": ("peak_to_peak", True)}       # amp_mode, amp_flagged


def amp_key(cfg):
    return cfg["amp_mode"] + ("+flagged" if cfg["amp_flagged"] and cfg["amp_mode"] == "peak_to_peak" else "")


def load(rec):
    import wfdb
    r = wfdb.rdrecord(f"{args.dir}/bidmc{rec}")
    names = [n.strip(", ") for n in r.sig_name]
    x = r.p_signal[:, names.index("II")].astype(float)
    n_nan = int(np.isnan(x).sum())
    if n_nan:
        k = np.arange(len(x)); ok = np.isfinite(x)
        x = np.interp(k, k[ok], x[ok])
    fs0 = float(r.fs)
    dur = len(x) / fs0
    ann = wfdb.rdann(f"{args.dir}/bidmc{rec}", "breath")
    br = {a: np.sort(np.array([s for s, n in zip(ann.sample, ann.aux_note) if n.strip() == a], dtype=float)) / fs0
          for a in ("ann1", "ann2")}
    starts = np.arange(0.0, dur - W + 1e-9, STEP)
    ref = np.full(len(starts), np.nan); n_one = 0
    for i, t0 in enumerate(starts):
        v = []
        for a in ("ann1", "ann2"):
            b = br[a][(br[a] >= t0) & (br[a] < t0 + W)]
            v.append(60.0 / np.mean(np.diff(b)) if len(b) >= 2 else np.nan)
        if np.all(np.isfinite(v)):
            n_one += 1
            if abs(v[0] - v[1]) <= AGREE:
                ref[i] = 0.5 * (v[0] + v[1])
    xr = frontend.resample(x, fs0)
    mods, info = {}, {}
    for filt in FILTERS:
        y = frontend.filter_ecg(xr, frontend.FS, 60.0, causal=(filt == "causal"))
        beats = frontend.detect(y, frontend.FS)
        nn = A.NNSeries.from_beats(beats, frontend.FS)
        info[filt] = dict(beats=len(beats), flagged=sum(b["flagged"] for b in beats), nn_cov=nn.coverage,
                          hr=60.0 * (len(beats) - 1) / (nn.span_s or np.nan))
        for key, (mode, fl) in AMP.items():
            mods[(filt, key)] = A.modulations(y, beats, frontend.FS, mode, fl)
    return dict(rec=rec, subject=SUBJECT[rec], starts=starts, ref=ref, n_windows=len(starts),
                n_both=n_one, mods=mods, info=info, n_nan=n_nan)


_SPECTRA = {}


def estimate(d, filt, cfg):
    """{method: array of estimates (NaN = withheld)} on the valid reference windows.
    The spectra depend only on some settings, so they are cached across the tuning grid."""
    cfg = {**A.CONFIG["breathing"], **cfg}
    idx = np.flatnonzero(np.isfinite(d["ref"]))
    key = (d["rec"], filt, amp_key(cfg), tuple(cfg["band_bpm"]), cfg["outlier_mad"], cfg["min_beat_coverage"],
           cfg["min_beats"], cfg["lomb_oversample"], cfg["window_s"])
    if key not in _SPECTRA:
        m = d["mods"][(filt, amp_key(cfg))]
        _SPECTRA[key] = [A.window_spectra(m, d["starts"][i], d["starts"][i] + W, cfg) for i in idx]
    out = {k: np.full(len(idx), np.nan) for k in METHODS}
    for j, sp in enumerate(_SPECTRA[key]):
        r = A.rate_from_spectra(sp, cfg)
        for k in METHODS:
            if r[k].value is not None:
                out[k][j] = r[k].value
    return out, d["ref"][idx]


def summarise(data, filt, cfg):
    """Per method: pooled and per-subject statistics, and the per-recording rows."""
    per_rec = {}
    for d in data:
        est, ref = estimate(d, filt, cfg)
        per_rec[d["rec"]] = (est, ref, d["subject"])
    res = {}
    for k in METHODS:
        e = np.concatenate([per_rec[r][0][k] for r in per_rec]); ref = np.concatenate([per_rec[r][1] for r in per_rec])
        ok = np.isfinite(e); err = e[ok] - ref[ok]
        subj = {}
        for r, (est, rf, sid) in per_rec.items():
            o = np.isfinite(est[k])
            s = subj.setdefault(sid, [0, 0, 0.0]); s[0] += len(rf); s[1] += int(o.sum()); s[2] += float(np.abs(est[k][o] - rf[o]).sum())
        smae = np.array([s[2] / s[1] for s in subj.values() if s[1] > 0])
        scov = np.array([s[1] / s[0] for s in subj.values() if s[0] > 0])
        res[k] = dict(n_ref=len(ref), n=int(ok.sum()), cov=ok.mean() if len(ref) else np.nan,
                      mae=float(np.abs(err).mean()) if len(err) else np.nan,
                      bias=float(err.mean()) if len(err) else np.nan,
                      sd=float(err.std(ddof=1)) if len(err) > 1 else np.nan,
                      within2=float((np.abs(err) <= 2).mean()) if len(err) else np.nan,
                      smae=smae, scov=scov, n_subj=len(subj), n_subj_rep=len(smae))
    return res, per_rec


def q(v):
    return (f"{np.median(v):.2f} [{np.percentile(v, 25):.2f}, {np.percentile(v, 75):.2f}]" if len(v) else "n/a")


def header(recs):
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "algorithms", "pan_tompkins.py",
                            "tp2_config.json", "validate_breathing_bidmc.py"], capture_output=True, text=True).stdout.strip()
    print(f"# ./validate_breathing_bidmc.py {' '.join(sys.argv[1:])}")
    print(f"# commit {commit}{' + uncommitted changes' if dirty else ''}; algorithms {A.VERSION}, "
          f"frozen: {A.CONFIG['frozen']}; detector {core.PT.CONFIG['version']} (tp2_config.json)")
    print(f"# breathing settings: {json.dumps(A.CONFIG['breathing'])}")
    print(f"# BIDMC {args.set} set: {len(set(SUBJECT.values()))} subjects, {len(recs)} recordings: {' '.join(recs)}")
    print(f"# reference: {W:g} s windows every {STEP:g} s, both annotators within {AGREE:g} breaths/min, their mean")
    print("# front end: lead II, 125 -> 256 Hz, 0.5-40 Hz with 60 Hz notch (causal = the phone's filter), tp2.1 beats\n")


def report(data, recs):
    header(recs)
    n_all = sum(d["n_windows"] for d in data); n_both = sum(d["n_both"] for d in data)
    n_ref = sum(int(np.isfinite(d["ref"]).sum()) for d in data)
    allref = np.concatenate([d["ref"][np.isfinite(d["ref"])] for d in data])
    print(f"windows: {n_all}; both annotators have 2+ breaths in {n_both}; they agree within {AGREE:g} in {n_ref} "
          f"({100*n_ref/n_all:.1f}% of all) = the reference windows")
    print(f"reference rate over those: median {np.median(allref):.1f}, range {allref.min():.1f}-{allref.max():.1f} breaths/min; "
          f"{100*np.mean(allref < 10):.1f}% below 10, {100*np.mean(allref > 25):.1f}% above 25")
    nan = [(d["rec"], d["n_nan"]) for d in data if d["n_nan"]]
    if nan:
        print("missing ECG samples, linearly interpolated: " + ", ".join(f"bidmc{r} {n}" for r, n in nan))
    print()
    for filt in FILTERS:
        res, per_rec = summarise(data, filt, {})
        raw, _ = summarise(data, filt, {"peak_share_min": 0.0})
        print(f"=== {filt} filter ===")
        print(f"{'method':18} {'gate':8} {'reported':>16} | {'MAE pooled':>10} {'bias':>6} {'LoA':>15} {'within 2':>8} | "
              f"{'MAE per subject, median [IQR]':>30} {'subjects':>9} | {'coverage per subject, median [IQR]':>34}")
        for k, name in (("rsa", "RSA"), ("ramp", "R amplitude"), ("fused", "fused")):
            for lab, r in (("on", res[k]), ("off", raw[k])):
                print(f"{name:18} {lab:8} {r['n']:6d}/{r['n_ref']:<6d} {100*r['cov']:3.0f}% | {r['mae']:10.2f} {r['bias']:+6.2f} "
                      f"{r['bias']-1.96*r['sd']:+6.1f}..{r['bias']+1.96*r['sd']:+5.1f} {100*r['within2']:7.0f}% | "
                      f"{q(r['smae']):>30} {r['n_subj_rep']:4d}/{r['n_subj']:<4d} | {q(100*r['scov']):>34}")
        print(f"\nper recording, {filt}: coverage % / MAE breaths/min (gate on)")
        print(f"{'rec':>4} {'subject':>7} {'beats':>5} {'HR':>5} {'flagged':>7} {'NN cov':>6} {'ref win':>7} {'ref rate':>11} | "
              + " | ".join(f"{n:^13}" for n in ("RSA", "R amplitude", "fused")))
        for d in data:
            est, ref, sid = per_rec[d["rec"]]
            i = d["info"][filt]
            cells = []
            for k in METHODS:
                o = np.isfinite(est[k])
                cells.append(f"{100*o.mean() if len(ref) else 0:4.0f}% " + (f"{np.abs(est[k][o]-ref[o]).mean():6.2f}" if o.any() else f"{'-':>6}"))
            rr = f"{ref.min():.0f}-{ref.max():.0f}" if len(ref) else "-"
            print(f"{d['rec']:>4} {sid:>7} {i['beats']:5d} {i['hr']:5.0f} {100*i['flagged']/max(1, i['beats']):6.1f}% "
                  f"{100*i['nn_cov']:5.0f}% {len(ref):7d} {rr:>11} | " + " | ".join(f"{c:^13}" for c in cells))
        print()
    print("A subject with no reported window has no MAE and is left out of the per-subject median; 'subjects' says how many are in it.")


def tune(data, recs):
    header(recs)
    grid = dict(amp=list(AMP), band_bpm=[[4.0, 40.0], [6.0, 40.0]],
                fusion=["average", "product", "agree", "best_share", "agree_or_ramp@0.4", "agree_or_ramp@0.5"],
                peak_share_min=[0.0, 0.2, 0.3, 0.4, 0.5, 0.6])
    print(f"tuning grid on the development subjects: {json.dumps(grid)}")
    print("every other setting as in config.json. Per cell: coverage % (pooled) / MAE per subject, median / its 75th "
          "percentile / MAE pooled / subjects with a value")
    print("RSA and R amplitude do not depend on the fusion rule; they are printed once per amp, band and share.")
    print("The other columns are the fused estimate under each rule; @x = ramp_alone_share.\n")

    def cell(r):
        sm = r["smae"]
        return (f"{100*r['cov']:4.0f}% {np.median(sm) if len(sm) else float('nan'):5.2f} "
                f"{np.percentile(sm, 75) if len(sm) else float('nan'):5.2f} {r['mae']:5.2f} {r['n_subj_rep']:2d}")
    best = None
    for filt in FILTERS:
        print(f"=== {filt} filter ===")
        print(f"{'amp':21} {'band':>5} {'share':>5} | {'RSA':^26} | {'R amplitude':^26} | "
              + " | ".join(f"{f:^26}" for f in grid["fusion"]))
        for amp, band, share in itertools.product(grid["amp"], grid["band_bpm"], grid["peak_share_min"]):
            base = dict(amp_mode=AMP[amp][0], amp_flagged=AMP[amp][1], band_bpm=band, peak_share_min=share)
            cells = []
            for i, fusion in enumerate(grid["fusion"]):
                rule, _, alone = fusion.partition("@")
                res, _ = summarise(data, filt, {**base, "fusion": rule, **({"ramp_alone_share": float(alone)} if alone else {})})
                if i == 0:
                    cells += [cell(res["rsa"]), cell(res["ramp"])]
                cells.append(cell(res["fused"]))
                r = res["fused"]
                if (filt == "causal" and band == [4.0, 40.0] and len(r["smae"])
                        and np.percentile(r["smae"], 75) <= 1.0 and (best is None or r["cov"] > best[0])):
                    best = (r["cov"], amp, share, fusion, r)
            print(f"{amp:21} {band[0]:2.0f}-{band[1]:<2.0f} {share:5.1f} | " + " | ".join(cells))
        print()
    print("Selection. The rule was written while looking at this table, which is what development data is for:")
    print("  1. band 4-40 breaths/min, fixed by requirement (paced breathing at 6/min must be inside the band),")
    print("     although 6-40 scores better here;")
    print("  2. among the 4-40 rows, the fused setting with the highest pooled coverage whose per-subject MAE has a")
    print("     75th percentile <= 1.0 breaths/min under the causal filter.")
    if best:
        cov, amp, share, fusion, r = best
        print(f"  -> amp {amp}, peak_share_min {share}, fusion {fusion}: coverage {100*cov:.0f}%, MAE per subject median "
              f"{np.median(r['smae']):.2f}, 75th percentile {np.percentile(r['smae'], 75):.2f}, pooled {r['mae']:.2f}, "
              f"{r['n_subj_rep']} of {r['n_subj']} subjects with a value")
    cur = A.CONFIG["breathing"]
    print(f"  config.json now holds: amp_mode {cur['amp_mode']}, amp_flagged {cur['amp_flagged']}, peak_share_min "
          f"{cur['peak_share_min']}, fusion {cur['fusion']}, ramp_alone_share {cur['ramp_alone_share']}, band {cur['band_bpm']}")


def main():
    recs = sorted(SUBJECT)
    import multiprocessing as mp
    with mp.Pool(min(args.jobs, len(recs))) as pool:
        data = pool.map(load, recs)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        (tune if args.tune else report)(data, recs)
    text = buf.getvalue(); print(text, end="")
    name = f"breathing_bidmc_{args.set}{'_tuning' if args.tune else ''}.txt"
    (HERE / "analysis" / name).write_text(text); print(f"saved {HERE / 'analysis' / name}")


if __name__ == "__main__":
    main()
