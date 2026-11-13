#!/usr/bin/env python3
"""Why does tp3 do worse than tp2.1 on some records? Diagnosis only; nothing is tuned.

    ./diagnose_tp3_records.py --dir <main>/data/incartdb --records I54 I55 I56 --lead II --mains 50 --label incart_patient24

For each record, under the causal filter: the annotated beat types, why each
timing point flags, how the beats correlate with the median beat, and how the
two timing points differ on beats both of them time. INCART was the held-out
set and is spent; this is written after its single run, to document a known
limitation, and no setting is changed because of it.

Saves analysis/tp3_diagnosis_<label>.txt.
"""
import argparse, collections, contextlib, io, os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, wfdb
import pan_tompkins as PT
import tp3_candidate as T3
from algorithms import NNSeries, frontend

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True); ap.add_argument("--records", nargs="+", required=True)
ap.add_argument("--lead", default="II"); ap.add_argument("--mains", type=float, default=50.0)
ap.add_argument("--label", required=True)
args = ap.parse_args()
FS = frontend.FS
BEAT = set("NLRejAaJSVEFP/fQ")


class Instrumented(PT.PanTompkins):
    def __init__(self, fs):
        super().__init__(fs); self.info = []

    def _finish(self):
        sign, t = self._polarity()
        ratio = float("nan")
        if t is not None:
            pos, neg = max(t), -min(t)
            ratio = max(pos, neg) / max(min(pos, neg), 1e-12)
        self.info.append((sign, ratio))
        return super()._finish()


def pct(v, qs=(5, 25, 50, 75, 95)):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    return " ".join(f"{np.percentile(v, q):.2f}" for q in qs) if len(v) else "n/a"


buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"# ./diagnose_tp3_records.py {' '.join(sys.argv[1:])}")
    print(f"# tp3: {T3.CONFIG['timing']} (frozen {T3.CONFIG['frozen']}); detector {PT.CONFIG['version']}; causal filter, lead {args.lead}\n")
    for rec in args.records:
        r = wfdb.rdrecord(f"{args.dir}/{rec}"); ann = wfdb.rdann(f"{args.dir}/{rec}", "atr")
        names = list(r.sig_name); ch = names.index(args.lead) if args.lead in names else 0
        y = frontend.filter_ecg(frontend.resample(r.p_signal[:, ch], float(r.fs)), FS, args.mains, causal=True)
        pt = Instrumented(FS)
        for v in y:
            pt.process(v)
        beats = pt.beats; info = pt.info[:len(beats)]
        b3 = T3.retime(y, beats, FS)
        sym = [s for s in ann.symbol if s in BEAT]
        at = np.array([s for s, q in zip(ann.sample, ann.symbol) if q in BEAT]) / float(r.fs)
        bt = np.array([b["bp"] for b in beats]) / FS
        near = np.array([int(np.argmin(np.abs(at - t))) for t in bt]); ok = np.abs(at[near] - bt) <= 0.15
        typ = np.array([sym[k] if o else "?" for k, o in zip(near, ok)])
        f2 = np.array([b["flagged"] for b in beats]); f3 = np.array([b["flagged"] for b in b3])
        print(f"=== {rec} ({(r.comments or [''])[1] if len(r.comments or []) > 1 else ''}; {(r.comments or [''])[-1]}) ===")
        print(f"annotated beats: {dict(collections.Counter(sym))}; detected {len(beats)}")
        print(f"tp2.1: flagged {100*f2.mean():.1f}%, NN coverage {100*NNSeries.from_beats(beats, FS).coverage:.1f}%; "
              f"median-beat lobe ratio (larger/smaller), percentiles 5 25 50 75 95: {pct([q for _, q in info])} (decided at 1.5)")
        print(f"tp3:   flagged {100*f3.mean():.1f}%, NN coverage {100*NNSeries.from_beats(b3, FS).coverage:.1f}%; why: "
              f"{dict(collections.Counter(b['why'] for b in b3 if b['flagged']))}")
        print(f"flagged share by annotated beat type (type: beats, tp2.1 %, tp3 %): "
              + "; ".join(f"{k}: {int((typ == k).sum())}, {100*f2[typ == k].mean():.0f}%, {100*f3[typ == k].mean():.0f}%"
                          for k in sorted(set(typ), key=lambda q: -(typ == q).sum())))
        rr = np.array([b["r"] for b in b3])
        for k in sorted(set(typ), key=lambda q: -(typ == q).sum())[:3]:
            print(f"  correlation with the median beat, type {k}, percentiles 5 25 50 75 95: {pct(rr[typ == k])}")
        segs = np.array_split(np.arange(len(beats)), 6)
        print("  through the record in six parts, flagged % tp2.1 / tp3: " + "  ".join(f"{100*f2[s].mean():.0f}/{100*f3[s].mean():.0f}" for s in segs))
        both = ~f2 & ~f3
        d = (np.array([b["pos"] for b in b3]) - np.array([b["pos"] for b in beats]))[both] / FS * 1000
        print(f"  beats timed by both: {int(both.sum())}; tp3 - tp2.1 position, ms, percentiles 5 25 50 75 95: {pct(d)}; "
              f"beat-to-beat change of that difference, sd {np.std(np.diff(d)):.2f} ms")
        edge = np.array([b["why"] == "best lag at the end of the range" for b in b3])
        off = (np.array([b["pos"] for b in beats]) - np.array([b["bp"] for b in beats])) / FS * 1000
        if edge.sum():
            print(f"  beats tp3 flags for 'best lag at the end of the range': {int(edge.sum())}, of which tp2.1 timed {int((edge & ~f2).sum())}. "
                  f"Where tp2.1 put the R peak relative to the 5-15 Hz peak, ms, percentiles 5 25 50 75 95: those beats {pct(off[edge & ~f2])}; "
                  f"all other beats tp2.1 timed {pct(off[~edge & ~f2])}. tp3 can shift by at most +-{T3.CONFIG['timing']['LAG'] / FS * 1000:.0f} ms.")
        lag = np.array([b["lag"] for b in b3])[~f3]
        print(f"  tp3 lags used (samples): {dict(sorted(collections.Counter(lag.tolist()).items()))}")
        nn2, nn3 = NNSeries.from_beats(beats, FS), NNSeries.from_beats(b3, FS)
        print(f"  intervals: {nn2.n_intervals}; unusable before cleaning tp2.1 {int(np.sum(~np.isfinite(np.array(PT.rr_history(beats, FS, depth=10**6)))))}, "
              f"tp3 {int(np.sum(~np.isfinite(np.array(PT.rr_history(b3, FS, depth=10**6)))))}; accepted after the 20% rule tp2.1 {nn2.n_accepted}, tp3 {nn3.n_accepted}\n")
text = buf.getvalue(); print(text, end="")
out = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "analysis" / f"tp3_diagnosis_{args.label}.txt"
out.write_text(text); print(f"saved {out}")
