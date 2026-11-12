#!/usr/bin/env python3
"""Session-level rules for the app, derived on development data.

    ./derive_session_rules.py --bidmc <main checkout>/data/bidmc \\
        --mitdb <main checkout>/data/mitdb <main checkout>/data/mitdb_heldout

A session is one recording of fixed length (180 s standard, 300 s extended in
the app). Two of its numbers are summaries the algorithms/ package does not
define, and the app has been using provisional values for their rules:

  heart rate      60000 / median of the beat-to-beat intervals in the session;
                  reported when there are at least hr_min_intervals of them
  breathing rate  median of the session's 32 s windows (one every 3 s) that
                  gave a fused rate; reported when at least
                  breathing_min_windows did and they span no more than
                  breathing_max_range_bpm

This script computes both exactly as session_reference.py on the app branch
does (beats inside the session only, NN series and modulations rebuilt from
them) and asks what those three numbers should be.

BREATHING: the 23 BIDMC development subjects (26 recordings of 480 s; the
held-out subjects are spent and are not touched). Sessions start every 60 s.
Reference for a session: per annotator 60 / mean time between the breaths in
it; kept when the two agree within 2 breaths/min; their mean. For every pair
(min windows, max range): how many sessions get a rate, and how wrong it is.

HEART RATE: all 48 MIT-BIH records, which are all development data from
13 Nov 2026 (docs/datasets.md). Sessions are consecutive 180 s stretches.
Reference: 60000 / median of the ANNOTATED beat-to-beat intervals of the whole
session. Estimate: the same statistic from only n of the detector's intervals,
taken either as one block (a session cut short) or scattered (intervals lost
to gaps). The question is how small n can be. MIT-BIH is an arrhythmia
database, so the tables are given for all sessions and for the sessions that
are in normal sinus rhythm throughout (rhythm annotation "(N" for the whole
session and at least 95% of beats of AAMI class N). In the others the heart
rate itself moves within three minutes, and a block of n intervals differs
from the whole session for that reason, not through any error of ours.

SELECTION, written while looking at the tables (development data):
  breathing  the smallest min-windows at which, for some range limit, no
             reported session is off by more than 2 breaths/min under either
             filter and either session length; then the range limit with the
             highest coverage (causal, 180 s), the smaller limit on a tie.
  heart rate the smallest n at which 95% of the scattered-interval estimates
             lie within 5 bpm of the session reference on ALL sessions, under
             both filters. 5 bpm is the project's month-1 limit of agreement.

Everything is run under the causal filter (the phone's); the zero-phase
figures are printed for comparison. Detector tp2.1, algorithms alg1, frozen.

Saves analysis/session_rules_dev.txt. The chosen values go into
algorithms/config.json under "session".
"""
import argparse, contextlib, io, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--bidmc", default="data/bidmc")
ap.add_argument("--mitdb", nargs="+", default=["data/mitdb", "data/mitdb_heldout"])
ap.add_argument("--jobs", type=int, default=6)
args = ap.parse_args()

import algorithms as A
from algorithms import core, frontend

HERE = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
FS = frontend.FS
SESSIONS = [180.0, 300.0]
BR_W, BR_STEP = A.CONFIG["breathing"]["window_s"], A.CONFIG["bidmc"]["step_s"]
AGREE = A.CONFIG["bidmc"]["ref_agree_bpm"]
SUBJECT = {rec: sid for sid, recs in A.CONFIG["bidmc"]["dev"].items() for rec in recs}
FILTERS = ["causal", "zero-phase"]
MIN_WINDOWS = [1, 2, 3, 5, 8, 10, 15, 20]
MAX_RANGE = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, None]
HR_N = [5, 10, 15, 20, 30, 45, 60, 90]
SEED = 20261113
BEAT = set("NLRejAaJSVEFP/fQ")
AAMI_N = set("NLRej")
PACED = {"102", "104", "107", "217"}


# ------------------------------------------------------------------ breathing
def bidmc_record(rec):
    import wfdb
    r = wfdb.rdrecord(f"{args.bidmc}/bidmc{rec}")
    names = [n.strip(", ") for n in r.sig_name]
    x = r.p_signal[:, names.index("II")].astype(float)
    if np.isnan(x).any():
        k = np.arange(len(x)); ok = np.isfinite(x); x = np.interp(k, k[ok], x[ok])
    fs0 = float(r.fs); dur = len(x) / fs0
    ann = wfdb.rdann(f"{args.bidmc}/bidmc{rec}", "breath")
    br = [np.sort(np.array([s for s, n in zip(ann.sample, ann.aux_note) if n.strip() == a], dtype=float)) / fs0
          for a in ("ann1", "ann2")]

    def ref_rate(t0, t1):
        v = []
        for b in br:
            b = b[(b >= t0) & (b < t1)]
            v.append(60.0 / np.mean(np.diff(b)) if len(b) >= 2 else np.nan)
        return 0.5 * (v[0] + v[1]) if np.all(np.isfinite(v)) and abs(v[0] - v[1]) <= AGREE else np.nan

    xr = frontend.resample(x, fs0)
    out = []
    for filt in FILTERS:
        y = frontend.filter_ecg(xr, FS, 60.0, causal=(filt == "causal"))
        beats_all = frontend.detect(y, FS)
        for S in SESSIONS:
            for t0 in np.arange(0.0, dur - S + 1e-9, 60.0):
                s0, s1 = int(round(t0 * FS)), int(round((t0 + S) * FS))
                beats = [b for b in beats_all if s0 <= b["pos"] < s1]
                ys = np.full(len(y), np.nan); ys[s0:s1] = y[s0:s1]
                mods = A.modulations(ys, beats, FS)
                rates, refs = [], []
                k = 0
                while k * BR_STEP <= S - BR_W + 1e-9:
                    w0 = t0 + k * BR_STEP
                    r_ = A.breathing_rate(mods, w0, w0 + BR_W)["fused"]
                    rates.append(r_.value if r_.ok else np.nan)
                    refs.append(ref_rate(w0, w0 + BR_W))
                    k += 1
                out.append(dict(rec=rec, subject=SUBJECT[rec], filt=filt, S=S, t0=t0, ref=ref_rate(t0, t0 + S),
                                rates=np.array(rates), refs=np.array(refs)))
    return out


def session_breathing(rates, n_min, rmax):
    v = rates[np.isfinite(rates)]
    if len(v) < n_min or (rmax is not None and len(v) and v.max() - v.min() > rmax):
        return None
    return float(np.median(v)) if len(v) else None


def breathing_tables(sess):
    for S in SESSIONS:
        for filt in FILTERS:
            ss = [s for s in sess if s["S"] == S and s["filt"] == filt and np.isfinite(s["ref"])]
            n_all = sum(1 for s in sess if s["S"] == S and s["filt"] == filt)
            nwin = len(ss[0]["rates"]) if ss else 0
            rng = np.array([np.nanmax(s["refs"]) - np.nanmin(s["refs"]) for s in ss if np.isfinite(s["refs"]).sum() >= 2])
            got = np.array([np.isfinite(s["rates"]).sum() for s in ss])
            est_rng = np.array([np.nanmax(s["rates"]) - np.nanmin(s["rates"]) for s in ss if np.isfinite(s["rates"]).sum() >= 2])
            print(f"=== breathing, {S:g} s sessions, {filt} filter: {n_all} sessions, {len(ss)} with a reference, "
                  f"{len(set(s['subject'] for s in ss))} subjects, {nwin} windows per session ===")
            print(f"what the REFERENCE does inside a session: range of its window rates, median {np.median(rng):.1f}, "
                  f"75th pct {np.percentile(rng, 75):.1f}, 90th {np.percentile(rng, 90):.1f}, max {rng.max():.1f} breaths/min")
            print(f"windows with a fused rate per session: median {np.median(got):.0f}, quartiles {np.percentile(got, 25):.0f}-"
                  f"{np.percentile(got, 75):.0f}; sessions with none {int((got == 0).sum())}. Range of the ESTIMATED window rates "
                  f"where there are 2+: median {np.median(est_rng):.1f}, 75th pct {np.percentile(est_rng, 75):.1f}, "
                  f"90th {np.percentile(est_rng, 90):.1f}, max {est_rng.max():.1f}")
            print("per cell: sessions reported % / MAE breaths/min / sessions off by more than 2 (count) / "
                  "MAE per subject, 75th pct / subjects with a session")
            print(f"{'min windows':>11} | " + " | ".join(f"{'range <= ' + (f'{r:g}' if r else 'any'):^27}" for r in MAX_RANGE))
            for n_min in MIN_WINDOWS:
                cells = []
                for rmax in MAX_RANGE:
                    err, subj = [], {}
                    for s in ss:
                        v = session_breathing(s["rates"], n_min, rmax)
                        if v is not None:
                            err.append(abs(v - s["ref"])); subj.setdefault(s["subject"], []).append(abs(v - s["ref"]))
                    if not err:
                        cells.append(f"{0:4.0f}% {'-':>5} {'-':>3} {'-':>5} {0:2d}"); continue
                    sm = [np.mean(v) for v in subj.values()]
                    cells.append(f"{100*len(err)/len(ss):4.0f}% {np.mean(err):5.2f} {int(np.sum(np.array(err) > 2)):3d} "
                                 f"{np.percentile(sm, 75):5.2f} {len(sm):2d}")
                print(f"{n_min:11d} | " + " | ".join(f"{c:^27}" for c in cells))
            print()


# ------------------------------------------------------------------ heart rate
def mitdb_record(path):
    import wfdb
    rec = os.path.basename(path)
    r = wfdb.rdrecord(path); ann = wfdb.rdann(path, "atr")
    names = list(r.sig_name)
    ch = names.index("MLII") if "MLII" in names else 0
    fs0 = float(r.fs)
    x = frontend.resample(r.p_signal[:, ch], fs0)
    at = np.array([s for s, sym in zip(ann.sample, ann.symbol) if sym in BEAT], dtype=float) / fs0
    an = np.array([sym in AAMI_N for sym in ann.symbol if sym in BEAT])
    rh = [(smp / fs0, aux.strip("\x00 ")) for smp, sym, aux in zip(ann.sample, ann.symbol, ann.aux_note) if sym == "+"]

    def sinus(t0, t1):
        """Normal sinus rhythm for the whole of [t0, t1) and >= 95% class-N beats."""
        cur = [lab for t, lab in rh if t <= t0]
        inside = [lab for t, lab in rh if t0 < t < t1]
        m = (at >= t0) & (at < t1)
        return bool(cur) and cur[-1] == "(N" and all(lab == "(N" for lab in inside) and an[m].mean() >= 0.95
    rng = np.random.default_rng(SEED + int(rec))
    out = []
    for filt in FILTERS:
        y = frontend.filter_ecg(x, FS, 60.0, causal=(filt == "causal"))
        bt = np.array([b["pos"] for b in frontend.detect(y, FS)]) / FS
        S = SESSIONS[0]
        for i in range(int((len(x) / FS) // S)):
            t0, t1 = i * S, (i + 1) * S
            a = at[(at >= t0) & (at < t1)]; b = bt[(bt >= t0) & (bt < t1)]
            if len(a) < 3 or len(b) < 3:
                continue
            ref = 60.0 / float(np.median(np.diff(a)))
            rr = np.diff(b)
            row = dict(rec=rec, filt=filt, ref=ref, n_int=len(rr), full=60.0 / float(np.median(rr)), block={}, scat={},
                       sinus=sinus(t0, t1))
            for n in HR_N:
                if len(rr) < n:
                    continue
                starts = [0] + list(rng.integers(0, len(rr) - n + 1, size=7))
                row["block"][n] = [60.0 / float(np.median(rr[s:s + n])) for s in starts]
                row["scat"][n] = [60.0 / float(np.median(rng.choice(rr, size=n, replace=False))) for _ in range(8)]
            out.append(row)
    return out


def hr_tables(rows):
    p95 = {}
    for filt in FILTERS:
        for label, keep in (("all sessions", lambda r: True), ("non-paced records", lambda r: r["rec"] not in PACED),
                            ("sessions in normal sinus rhythm throughout", lambda r: r["sinus"])):
            rr = [r for r in rows if r["filt"] == filt and keep(r)]
            print(f"=== heart rate, 180 s sessions, {filt} filter, {label}: {len(rr)} sessions from "
                  f"{len(set(r['rec'] for r in rr))} records ===")
            e = np.array([r["full"] - r["ref"] for r in rr])
            print(f"every interval of the session (median {np.median([r['n_int'] for r in rr]):.0f} of them): median error "
                  f"{np.median(e):+.2f}, 95th pct |error| {np.percentile(np.abs(e), 95):.1f}, largest {np.abs(e).max():.1f}, "
                  f"over 5 bpm in {int(np.sum(np.abs(e) > 5))} sessions")
            print(f"{'n intervals':>11} | " + " | ".join(f"{h:^52}" for h in ("one block of n", "n scattered over the session")))
            print(f"{'':>11} | " + " | ".join(f"{'median e':>8} {'95th |e|':>8} {'>5 bpm':>7} {'worst record: >5 bpm':>24}" for _ in range(2)))
            for n in HR_N:
                cells = []
                for kind in ("block", "scat"):
                    e = np.array([v - r["ref"] for r in rr for v in r[kind].get(n, [])])
                    per = {}
                    for r in rr:
                        for v in r[kind].get(n, []):
                            per.setdefault(r["rec"], []).append(abs(v - r["ref"]) > 5)
                    worst = max(per, key=lambda k: np.mean(per[k]))
                    cells.append(f"{np.median(e):+8.2f} {np.percentile(np.abs(e), 95):8.1f} {100*np.mean(np.abs(e) > 5):6.1f}% "
                                 f"{worst:>17} {100*np.mean(per[worst]):5.0f}%")
                    if kind == "scat" and label == "all sessions":
                        p95[(filt, n)] = float(np.percentile(np.abs(e), 95))
                print(f"{n:11d} | " + " | ".join(f"{c:^52}" for c in cells))
            print()
    return p95


def choose_breathing(sess):
    def stats(S, filt, n_min, rmax):
        ss = [s for s in sess if s["S"] == S and s["filt"] == filt and np.isfinite(s["ref"])]
        err = [abs(v - s["ref"]) for s in ss for v in [session_breathing(s["rates"], n_min, rmax)] if v is not None]
        return len(err) / len(ss), int(np.sum(np.array(err) > 2)) if err else 0
    for n_min in MIN_WINDOWS:
        ok = [r for r in MAX_RANGE if all(stats(S, f, n_min, r)[1] == 0 for S in SESSIONS for f in FILTERS)]
        if ok:
            best = max(ok, key=lambda r: (round(stats(SESSIONS[0], "causal", n_min, r)[0], 6), -(r or 1e9)))
            return n_min, best, {(S, f): stats(S, f, n_min, best) for S in SESSIONS for f in FILTERS}
    return None, None, {}


def main():
    import multiprocessing as mp
    mit = sorted(str(p.with_suffix("")) for d in args.mitdb for p in pathlib.Path(d).glob("*.hea"))
    with mp.Pool(args.jobs) as pool:
        sess = [s for part in pool.map(bidmc_record, sorted(SUBJECT)) for s in part]
        rows = [r for part in pool.map(mitdb_record, mit) for r in part]
    commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"# ./derive_session_rules.py {' '.join(sys.argv[1:])}")
        print(f"# commit {commit}; algorithms {A.VERSION} (frozen {A.CONFIG['frozen']}); detector {core.PT.CONFIG['version']}")
        print(f"# breathing: {json.dumps({k: v for k, v in A.CONFIG['breathing'].items() if k != 'selection'})}")
        print(f"# BIDMC development subjects: {len(set(SUBJECT.values()))}, recordings {' '.join(sorted(SUBJECT))}; sessions start every 60 s")
        print(f"# MIT-BIH: {len(mit)} records, MLII where present; sessions are consecutive 180 s stretches; seed {SEED}")
        print(f"# session rules now in algorithms/config.json: {json.dumps(A.CONFIG.get('session', 'none yet'))}\n")
        breathing_tables(sess)
        p95 = hr_tables(rows)
        n_min, rmax, st = choose_breathing(sess)
        print("SELECTION (rules in the docstring of this script)")
        print(f"  breathing_min_windows {n_min}, breathing_max_range_bpm {rmax}: sessions reported "
              + ", ".join(f"{100*c:.0f}% ({S:g} s, {f})" for (S, f), (c, _) in st.items()) + "; none off by more than 2 breaths/min")
        good = [n for n in HR_N if all(p95[(f, m)] <= 5.0 for f in FILTERS for m in HR_N if m >= n)]
        print(f"  hr_min_intervals {good[0] if good else 'none'}: 95th pct |error| of n scattered intervals, all sessions: "
              + ", ".join(f"{p95[(f, good[0])]:.1f} bpm ({f})" for f in FILTERS) if good else "  hr_min_intervals: no n meets the rule")
    text = buf.getvalue(); print(text, end="")
    out = HERE / "analysis" / "session_rules_dev.txt"
    out.write_text(text); print(f"saved {out}")


if __name__ == "__main__":
    main()
