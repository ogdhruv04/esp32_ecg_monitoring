#!/usr/bin/env python3
"""Per-window features of WESAD subjects, one subject at a time
(docs/wesad_plan.md, sections 3, 4 and 7 A1/A2).

    ./wesad_features.py --zip <main>/data/wesad_download/WESAD.zip \
        --cache <main>/data/wesad_cache --out <main>/data/wesad_features --subjects S2 S3

Each subject is extracted from the archive if its cache file is missing, then
processed and released before the next. Writes, per subject:
  <out>/<S>.csv        one row per 180 s window: part, t0, t1, the features
                       (<block>.<feature>, NaN = withheld) and info columns
                       (ecg_info.*, bvp_info.*, sync.*, match.*)
  <out>/<S>.json       durations, label runs, condition order, run time, peak memory
Feature tables stay in data/ (derived from data for scientific, non-commercial
use) and are not committed. No classification happens here.
"""
import argparse, json, os, resource, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs under python -I
import numpy as np
import pandas as pd
from scipy import signal as sps

ap = argparse.ArgumentParser()
ap.add_argument("--zip", required=True)
ap.add_argument("--cache", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--subjects", nargs="+", required=True)
args = ap.parse_args()

from algorithms import wesad, ppg, eda, temp, arousal, NNSeries
from algorithms import frontend
from algorithms.core import CONFIG

W = CONFIG["wesad"]
FS_ECG = frontend.FS                                  # 256


def ecg_beats(rec):
    x = sps.resample_poly(rec.ecg.astype(float), 128, 350)        # 700 -> 256 Hz
    y = frontend.filter_ecg(x, FS_ECG, W["mains_hz"], causal=True)
    beats = frontend.detect(y, FS_ECG)
    return beats, NNSeries.from_beats(beats, FS_ECG)


def process(subject):
    t_start = time.time()
    path = os.path.join(args.cache, f"{subject}.npz")
    rec = wesad.load(args.cache, subject) if os.path.exists(path) else wesad.extract(args.zip, args.cache, subject)
    parts = rec.parts()
    wins = wesad.windows(parts)

    beats, nn_ecg = ecg_beats(rec)
    beat_t = np.array([b["pos"] for b in beats]) / FS_ECG
    t_ecg = time.time() - t_start

    pulses = ppg.detect(ppg.bandpass(rec.bvp, W["fs"]["bvp"]), W["fs"]["bvp"])
    nn_p = ppg.pulse_intervals(pulses)
    delays = ppg.apparent_delays(beat_t, pulses.t)

    eda_w = rec.eda_wrist.astype(float)
    d_w = eda.decompose(eda_w)
    eda_c = eda.to_rate(rec.eda_chest, W["fs"]["chest"])
    d_c = eda.decompose(eda_c)
    peaks05_w = eda.scr_peaks(d_w.phasic, min_us=CONFIG["eda"]["scr_min_us_sensitivity"])
    temp_c = eda.to_rate(rec.temp_chest, W["fs"]["chest"])
    chest_temp_ok = subject not in W["chest_temp_withheld"]

    rows = []
    for part, t0, t1 in wins:
        r = dict(part=part, t0=t0, t1=t1)
        v, info = arousal.ecg_features(nn_ecg.window(t0, t1))
        r.update({f"ecg.{k}": x for k, x in v.items()}); r.update({f"ecg_info.{k}": x for k, x in info.items()})
        v, info = ppg.window_features(pulses, nn_p, t0, t1)
        r.update({f"bvp.{k}": x for k, x in v.items()}); r.update({f"bvp_info.{k}": x for k, x in info.items()})
        for block, x, d in (("eda_wrist", eda_w, d_w), ("eda_chest", eda_c, d_c)):
            r.update({f"{block}.{k}": x_ for k, x_ in eda.window_features(x, d, t0, t1).items()})
        i0, i1 = int(np.ceil(t0 * 4 - 1e-9)), int(np.ceil(t1 * 4 - 1e-9))
        ok = np.isfinite(r["eda_wrist.scl"])
        r["eda_wrist.scr_rate_05"] = float(np.sum((peaks05_w >= i0) & (peaks05_w < i1)) / ((t1 - t0) / 60)) if ok else np.nan
        r["temp_wrist.temp_slope"] = temp.slope(rec.temp_wrist, t0, t1)
        r["temp_chest.temp_slope"] = temp.slope(temp_c, t0, t1) if chest_temp_ok else np.nan
        k = (beat_t >= t0) & (beat_t < t1)
        dk = delays[k]
        r["sync.n"] = int(np.isfinite(dk).sum())
        r["sync.delay_ms"] = float(1000 * np.nanmedian(dk)) if r["sync.n"] else np.nan
        r["sync.delay_iqr_ms"] = float(1000 * np.subtract(*np.nanpercentile(dk, [75, 25]))) if r["sync.n"] else np.nan
        if r["sync.n"]:
            pk = (pulses.t >= t0 + r["sync.delay_ms"] / 1000) & (pulses.t < t1 + r["sync.delay_ms"] / 1000)
            tp, nb, npl = ppg.match(beat_t[k], pulses.t[pk], r["sync.delay_ms"] / 1000, W["match_tol_s"])
        else:
            tp, nb, npl = 0, int(k.sum()), 0
        r.update({"match.tp": tp, "match.beats": nb, "match.pulses": npl})
        rows.append(r)

    os.makedirs(args.out, exist_ok=True)
    df = pd.DataFrame(rows)
    tmp = os.path.join(args.out, f".{subject}.csv.tmp")
    df.to_csv(tmp, index=False); os.replace(tmp, os.path.join(args.out, f"{subject}.csv"))
    meta = dict(subject=subject, durations_s=rec.durations(), order=rec.order(),
                runs=[(c, round(a, 2), round(b, 2)) for c, a, b in rec.runs()],
                parts={k: [round(a, 2), round(b, 2)] for k, (a, b) in parts.items()},
                windows=int(len(df)), beats=len(beats), beats_flagged=int(sum(b["flagged"] for b in beats)),
                pulses=len(pulses), eda_wrist_min_us=float(eda_w.min()), eda_chest_min_us=float(eda_c.min()),
                ecg_s=round(t_ecg, 1), total_s=round(time.time() - t_start, 1),
                peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
                config_version=CONFIG["version"], wesad_frozen=W["frozen"])
    with open(os.path.join(args.out, f"{subject}.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"{subject}: {len(df)} windows, {len(beats)} beats, {len(pulses)} pulses, "
          f"{meta['total_s']} s, peak {meta['peak_rss_mb']} MB", flush=True)


for s in args.subjects:
    if s not in wesad.SUBJECTS:
        sys.exit(f"unknown subject {s}")
    process(s)
