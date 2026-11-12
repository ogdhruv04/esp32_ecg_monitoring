#!/usr/bin/env python3
"""Write fixtures for the app's algorithm ports (android_app/.../test/resources/session).

Every measure the Session report shows is ported to Kotlin from algorithms/,
and must give the Python value on the same input. Two kinds of fixture:

  nn_<case>.csv / nn_<case>_expected.tsv / nn_<case>_raw.tsv
      An NN series (beat times, intervals with NaN holes) from a real
      recording, every HRV measure's gated Result on it, and the ungated
      arithmetic (SDNN, SD1/SD2, LF/HF band power, DFA alpha1 ...) on the same
      series, so a measure whose minimum window is not met is still checked
      number for number. Checked by HrvParityTest.
  session_<case>_expected.tsv / session_<case>_windows.tsv
      The whole Session report (session_reference.py) on a real recording fed
      sample by sample, and the fused breathing rate of every 32 s window.
      Checked by SessionParityTest, which runs BeatDetector + SessionRecorder.

Inputs are float32 filtered samples with lost-sample counts (value,skip_before),
the format of make_parity_fixtures.py; four of its inputs are reused as they
are. The two test-board recordings (27 Oct 2026) are the only captures of ours
longer than 3 minutes, so they are the only ones that can hold a full session.

    ./make_session_fixtures.py && (cd android_app && ./gradlew testDebugUnitTest)

Also writes analysis/app_session_reference.txt: the reference reports.
"""
import csv, math, pathlib, subprocess
import numpy as np
from scipy import signal as sps
import algorithms as A
from algorithms import NNSeries, hrv_freq, hrv_nonlinear
import session_reference as S

FS = 256.0
NN_KEYS = S.HRV_KEYS + ["dfa_alpha1", "sampen"]     # every ported HRV measure
PARITY = pathlib.Path("android_app/app/src/test/resources/parity")
OUT = pathlib.Path("android_app/app/src/test/resources/session")
REPORT = pathlib.Path("analysis/app_session_reference.txt")
TESTBOARD = {"tb01": "captures/20261027_173714_testboard01.csv",
             "tb02": "captures/20261027_174352_testboard02.csv"}


def causal_filter(x):
    """As make_parity_fixtures.py: approximates EcgFilter.kt."""
    y = sps.sosfilt(sps.butter(4, 0.5, "highpass", fs=FS, output="sos"), x)
    for f in (50.0, 100.0):
        b, a = sps.iirnotch(f, 30.0, fs=FS); y = sps.lfilter(b, a, y)
    return sps.sosfilt(sps.butter(4, 40.0, "lowpass", fs=FS, output="sos"), y)


def read_input(path):
    v, s = [], []
    with open(path) as f:
        next(f)
        for line in f:
            if line.strip():
                a, b = line.split(",")
                v.append(np.float32(float(a))); s.append(int(b))
    return np.array(v, dtype=np.float32), np.array(s, dtype=int)


def testboard_input(path, seconds):
    """Received samples in index order (duplicates dropped, ETAG 6/7 dropped),
    filtered as the phone would, with each missing run as a skip before the
    next sample. Truncated at `seconds` of absolute time."""
    idx, val = [], []
    seen = set()
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                i, e, x = int(r["index"]), int(r["etag"]), float(r["value"])
            except (TypeError, ValueError):
                continue
            if e in (6, 7) or i in seen:
                continue
            seen.add(i); idx.append(i); val.append(x)
    idx = np.array(idx); order = np.argsort(idx, kind="stable")
    idx, val = idx[order], np.array(val)[order]
    y = causal_filter(val).astype(np.float32)
    skips = np.zeros(len(y), int)
    skips[1:] = np.diff(idx) - 1
    keep = (idx - idx[0]) < seconds * FS
    return y[keep], skips[keep]


def write_input(name, v, s):
    with open(OUT / f"{name}_input.csv", "w") as f:
        f.write("value,skip_before\n")
        for a, b in zip(v, s):
            f.write(f"{repr(float(a))},{int(b)}\n")


def fmt(x):
    return "nan" if x is None or x != x else repr(float(x))


def write_results(path, rows):
    """rows: (key, Result). Tab-separated, since a reason may hold commas."""
    with open(path, "w") as f:
        f.write("key\tvalue\twithheld\tn_used\tvalid_s\tspan_s\tcoverage\n")
        for k, r in rows:
            f.write(f"{k}\t{fmt(r.value)}\t{r.withheld or ''}\t{r.n_used}\t{fmt(r.valid_s)}\t"
                    f"{fmt(r.span_s)}\t{fmt(r.coverage)}\n")


def raw_values(nn):
    """The arithmetic of each measure with no minimum-window check."""
    v, t = nn.values, nn.times
    a, b = nn.pairs()
    out = {
        "rmssd": math.sqrt(np.mean((b - a) ** 2)) if len(a) else math.nan,
        "pnn50": 100.0 * float(np.mean(np.abs(b - a) > 50.0)) if len(a) else math.nan,
        "sdnn": float(np.std(v, ddof=1)) if len(v) > 1 else math.nan,
        "sd1": float(np.std((a - b) / math.sqrt(2.0), ddof=1)) if len(a) > 1 else math.nan,
        "sd2": float(np.std((a + b) / math.sqrt(2.0), ddof=1)) if len(a) > 1 else math.nan,
        "lf": hrv_freq.band_power(t, v, hrv_freq.BANDS["lf"]) if len(v) > 2 else math.nan,
        "hf": hrv_freq.band_power(t, v, hrv_freq.BANDS["hf"]) if len(v) > 2 else math.nan,
    }
    runs = nn.runs(min_len=hrv_nonlinear.SCALE_MAX)
    out["dfa_alpha1"] = hrv_nonlinear.dfa_alpha1_raw(runs) if runs else math.nan
    m = hrv_nonlinear.SAMPEN_M
    sruns = nn.runs(min_len=m + 1)
    out["sampen"] = (hrv_nonlinear.sample_entropy_raw(sruns, float(np.std(v, ddof=1)))[0]
                     if sruns and len(v) > 1 else math.nan)
    return out


def write_nn(name, nn):
    with open(OUT / f"nn_{name}.csv", "w") as f:
        f.write("beat_t,nn_ms\n")
        f.write(f"{fmt(nn.beat_t[0])},\n")
        for t, m in zip(nn.beat_t[1:], nn.nn_ms):
            f.write(f"{fmt(t)},{fmt(m)}\n")
    h = A.hrv(nn)
    write_results(OUT / f"nn_{name}_expected.tsv", [(k, h[k]) for k in NN_KEYS])
    raw = raw_values(nn)
    with open(OUT / f"nn_{name}_raw.tsv", "w") as f:
        for k, x in raw.items():
            f.write(f"{k}\t{fmt(x)}\n")
    return h, raw


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = []
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    lines.append(f"# ./make_session_fixtures.py (commit {commit}); session {S.VERSION}, "
                 f"algorithms {A.VERSION} (frozen {A.CONFIG['frozen']}), detector tp2.1")
    lines.append("# causal filter (the phone's), detector run sample by sample; session = beats located by "
                 "s1 + tail whose position lies in [s0, s1)")

    inputs = {k: read_input(PARITY / f"{k}_input.csv") for k in ("chest", "finger", "artifact_gaps", "polarity_flip")}
    for k, p in TESTBOARD.items():
        v, s = testboard_input(p, 300.0)
        write_input(k, v, s)
        inputs[k] = (v, s)

    # ---- per-measure fixtures: the NN series of each whole input
    lines.append("\n== NN series of each whole input: every HRV measure, gated ==")
    stitched = []
    for name, (v, s) in inputs.items():
        pt, _ = S.run_detector(v, s, 10**12)
        nn = NNSeries.from_beats(pt.beats, FS)
        h, raw = write_nn(name, nn)
        if name in ("finger", "tb01", "tb02"):
            stitched.append(nn.values)
        lines.append(f"{name:14} {len(pt.beats)} beats, {nn.n_accepted}/{nn.n_intervals} accepted "
                     f"(coverage {100 * nn.coverage:.1f}%), {nn.valid_s:.1f} s valid")
        for k in NN_KEYS:
            lines.append(f"    {h[k]}")
    # Every gate passes only on a long series with no holes, which none of our
    # recordings has: the accepted intervals of three recordings joined end to
    # end. Real intervals, artificial junctions; for the arithmetic only.
    st = NNSeries.from_intervals(np.concatenate(stitched), clean=False)
    h, _ = write_nn("stitched", st)
    lines.append(f"{'stitched':14} accepted intervals of finger + tb01 + tb02 joined: {st.n_intervals} intervals, "
                 f"{st.valid_s:.1f} s")
    for k in NN_KEYS:
        lines.append(f"    {h[k]}")

    # ---- session fixtures
    tail = int(S.SESSION["tail_s"] * FS)
    # (input, start s, duration s, kind). No capture of ours holds a 5-minute
    # session, so the extended case is tb02 over 270 s: the kind decides which
    # measures are on the report, the duration only what data they get.
    std = S.SESSION["kinds"]["standard"]["duration_s"]
    cases = {"finger": ("finger", 10.0, 90.0, "standard"), "chest": ("chest", 5.0, 50.0, "standard"),
             "artifact_gaps": ("artifact_gaps", 5.0, 50.0, "standard"),
             "tb01": ("tb01", 20.0, std, "standard"), "tb02": ("tb02", 20.0, std, "standard"),
             "tb02_ext": ("tb02", 20.0, 270.0, "extended")}
    lines.append(f"# session-level rules: {S.RULES} ({'PROVISIONAL, not yet in algorithms/config.json' if S.RULES_PROVISIONAL else 'algorithms/config.json'}); "
                 f"breathing window step {S.BR_STEP_S:g} s (algorithms/config.json bidmc.step_s)")
    lines.append("\n== Session reports (session_reference.py) ==")
    with open(OUT / "session_cases.tsv", "w") as f:
        f.write("case\tinput\ts0\ts1\tkind\n")
        for name, (inp, start, dur, kind) in cases.items():
            s0 = int(start * FS); s1 = s0 + int(dur * FS)
            src = f"parity/{inp}_input.csv" if inp in ("chest", "finger", "artifact_gaps") else f"session/{inp}_input.csv"
            f.write(f"{name}\t{src}\t{s0}\t{s1}\t{kind}\n")
            v, s = inputs[inp]
            pt, y = S.run_detector(v, s, s1 + tail)
            assert len(y) >= s1 + tail, f"{name}: input too short for the session"
            rep = S.session_report(pt, y, s0, s1, kind=kind)
            write_results(OUT / f"session_{name}_expected.tsv", [(k, rep[k]) for k in S.keys(kind)])
            with open(OUT / f"session_{name}_windows.tsv", "w") as g:
                g.write("w0\tvalue\twithheld\tn_used\tcoverage\n")
                for w0, r in rep["_windows"]:
                    g.write(f"{fmt(w0)}\t{fmt(r.value)}\t{r.withheld or ''}\t{r.n_used}\t{fmt(r.coverage)}\n")
            nn = rep["_nn"]
            lost = int(np.isnan(y[s0:s1]).sum())
            nw = sum(r.ok for _, r in rep["_windows"])
            lines.append(f"{name:14} {kind} session {start:g}-{start + dur:g} s ({dur:g} s): {len(rep['_beats'])} beats, "
                         f"{lost} samples lost, NN coverage {100 * nn.coverage:.1f}%, {nn.valid_s:.1f} s valid; "
                         f"breathing windows with a rate {nw}/{len(rep['_windows'])}")
            for k in S.keys(kind):
                lines.append(f"    {rep[k]}")
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"wrote {OUT}/ and {REPORT}")


if __name__ == "__main__":
    main()
