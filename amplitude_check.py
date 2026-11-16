#!/usr/bin/env python3
"""Amplitude and noise floor of a capture, in raw codes and nominal microvolts.

    ./amplitude_check.py captures/<a>.csv [captures/<b>.csv ...] [--label L]
    ./amplitude_check.py --idle captures/<no-electrode>.csv      # no beats expected
    ./amplitude_check.py --cal  captures/<mode c>.csv            # calibration square wave

For the amplitude investigation (docs/amplitude_investigation.md) and its bench
A/B test: run it on a 'd' capture and an 'e' capture and compare the lines.

ECG mode (default). Beats are found on a zero-phase 0.5-40 Hz copy; every
figure is then measured on the RAW codes (what the chip's own 0.5 Hz high-pass
and 40 Hz low-pass left), each beat referred to its own baseline window:
  qrs_pp   peak-to-peak of the median beat within +-60 ms of the beat position
  r        largest deflection from baseline in that window (signed)
  t        largest deflection from baseline 150-400 ms after it (signed)
  noise    what does not repeat from beat to beat: each beat minus the median
           beat, rms in the 100 ms window ending 250 ms before the beat, linear
           trend removed; median over beats. (Without subtracting the median
           beat the window holds the previous T wave at 100 bpm.)
The nominal scale is 1 mV = 2621.44 codes (datasheet check #23, unverified).

--idle: no beat detection; sd, peak-to-peak and mains share in 5 s windows,
and the same 100 ms detrended rms as the ECG mode's noise, for comparison.

--cal: mode 'c' is a 50% duty square wave at FMSTR/2048 = 16 Hz, exactly 16
samples per period at 256 SPS, so the samples are folded on index mod 16. The
40 Hz low-pass removes the harmonics, so the step is NOT read off a plateau:
it is taken from the fundamental, step = (pi/2) x fundamental amplitude.
A 1.0 mV step predicts a fundamental of 1668.9 codes on the nominal scale.

Writes analysis/amplitude_<label>.txt. Not a validation of anything.
"""
import argparse, csv, datetime, pathlib, sys
import numpy as np
import scipy.signal as sps
import pan_tompkins

FS = 256
CODES_PER_MV = 2 ** 17 * 20 / 1000.0          # nominal, datasheet check #23
AMP_NOISE_UV = (0.53, 1.0)                    # typ, max rms, 0.05-40 Hz, gain 20 (datasheet p.4)

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="+")
ap.add_argument("--label", default=None)
ap.add_argument("--skip-s", type=float, default=10.0, help="settling time dropped from the start")
ap.add_argument("--mains", type=float, default=50.0)
ap.add_argument("--idle", action="store_true", help="no electrodes: window statistics only")
ap.add_argument("--cal", action="store_true", help="mode 'c' capture: measure the calibration step")
ap.add_argument("--cal-mv", type=float, default=1.0, help="differential step the source is set to")
args = ap.parse_args()


def load(path):
    idx, val = [], []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["etag"] in ("0", "2"):
                idx.append(int(r["index"])); val.append(int(r["value"]))
    idx = np.array(idx); val = np.array(val, dtype=float)
    keep = idx - idx[0] >= args.skip_s * FS
    idx, val = idx[keep], val[keep]
    return idx, val, int(np.sum(np.diff(idx) != 1))


def uv(codes):
    return codes / CODES_PER_MV * 1000.0


def ecg(idx, x):
    y = sps.sosfiltfilt(sps.butter(4, [0.5, 40.0], "bandpass", fs=FS, output="sos"), x - np.median(x))
    b, a = sps.iirnotch(args.mains, 30.0, fs=FS); y = sps.filtfilt(b, a, y)
    det = np.round(pan_tompkins.detect(y, FS)).astype(int)
    lo, hi = int(0.35 * FS), int(0.45 * FS)
    b0, b1 = 0, int(0.10 * FS)                 # baseline / noise window: -350..-250 ms
    beats = []
    for d in det:
        if d - lo < 0 or d + hi >= len(x):
            continue
        w = x[d - lo:d + hi + 1]
        beats.append(w - np.median(w[b0:b1]))
    beats = np.array(beats)
    m = np.median(beats, axis=0)
    noise = [detrended_rms(b[b0:b1] - m[b0:b1]) for b in beats]
    q = m[lo - int(0.06 * FS):lo + int(0.06 * FS) + 1]
    tw = m[lo + int(0.15 * FS):lo + int(0.40 * FS) + 1]
    r = q[np.argmax(np.abs(q))]; tt = tw[np.argmax(np.abs(tw))]
    return dict(beats=len(beats), qrs_pp=q.max() - q.min(), r=r, t=tt,
                noise=float(np.median(noise)), noise_p10=float(np.percentile(noise, 10)))


def detrended_rms(w):
    t = np.arange(len(w))
    return float(np.std(w - np.polyval(np.polyfit(t, w, 1), t)))


def mains_share(x):
    x = x - x.mean()
    X = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / FS)
    band = (np.abs(f - args.mains) <= 0.4) | (np.abs(f - 2 * args.mains) <= 0.4)
    return X[band].sum() / X[1:].sum()


def idle(x):
    n = 5 * FS
    wins = [x[s:s + n] for s in range(0, len(x) - n + 1, n)]
    k = int(0.10 * FS)
    short = [detrended_rms(x[s:s + k]) for s in range(0, len(x) - k + 1, k)]
    return dict(windows=len(wins), sd=float(np.median([w.std() for w in wins])), short=float(np.median(short)),
                pp=float(np.median([w.max() - w.min() for w in wins])),
                mains=float(np.median([mains_share(w) for w in wins])))


def cal(idx, x):
    P = 16
    ph = idx % P
    wave = np.array([x[ph == k].mean() for k in range(P)])
    wave -= wave.mean()
    F = np.fft.rfft(wave) * 2 / P
    a1, a3 = abs(F[1]), abs(F[3])
    resid = np.median([x[ph == k].std() for k in range(P)])
    step = np.pi / 2 * a1
    return dict(periods=len(x) // P, a1=a1, a3=a3, pp=wave.max() - wave.min(), resid=float(resid),
                step=step, codes_per_mv=step / args.cal_mv)


out = []
p = out.append
mode = "cal" if args.cal else "idle" if args.idle else "ecg"
p(f"# amplitude_check.py, mode {mode}; raw codes, ETAG 0/2 only, first {args.skip_s:g} s dropped")
p(f"# nominal scale {CODES_PER_MV:.2f} codes/mV (datasheet check #23, unverified); "
  f"amplifier noise {AMP_NOISE_UV[0]} typ / {AMP_NOISE_UV[1]} max uV rms in 0.05-40 Hz (datasheet p.4) "
  f"= {AMP_NOISE_UV[0] * CODES_PER_MV / 1000:.2f} / {AMP_NOISE_UV[1] * CODES_PER_MV / 1000:.2f} codes")
if mode == "ecg":
    p("file\tseconds\tindex_gaps\traw_mean\traw_median\tbeats\tqrs_pp_codes\tqrs_pp_uV\tr_codes\tt_codes\t|t/r|\t"
      "noise_rms_codes\tnoise_rms_uV\tnoise_p10_codes\tqrs_pp/noise")
elif mode == "idle":
    p("file\tseconds\tindex_gaps\traw_mean\twindows\tsd_codes\tsd_uV\tpp_codes\tmains_share\trms_100ms_codes")
else:
    p(f"# predicted for a {args.cal_mv:g} mV step on the nominal scale: fundamental "
      f"{2 / np.pi * args.cal_mv * CODES_PER_MV:.1f} codes, step {args.cal_mv * CODES_PER_MV:.1f} codes")
    p("file\tseconds\tindex_gaps\tperiods\tfund_codes\tthird_codes\tfolded_pp_codes\tresid_sd_codes\t"
      "step_codes\tcodes_per_mV\tmeasured/nominal")
for path in args.files:
    idx, x, gaps = load(path)
    name = pathlib.Path(path).name
    head = f"{name}\t{len(x) / FS:.1f}\t{gaps}"
    if mode == "ecg":
        r = ecg(idx, x)
        p(f"{head}\t{x.mean():.1f}\t{np.median(x):.0f}\t{r['beats']}\t{r['qrs_pp']:.0f}\t{uv(r['qrs_pp']):.1f}\t"
          f"{r['r']:.0f}\t{r['t']:.0f}\t{abs(r['t'] / r['r']):.2f}\t{r['noise']:.2f}\t{uv(r['noise']):.2f}\t"
          f"{r['noise_p10']:.2f}\t{r['qrs_pp'] / r['noise']:.0f}")
    elif mode == "idle":
        r = idle(x)
        p(f"{head}\t{x.mean():.1f}\t{r['windows']}\t{r['sd']:.2f}\t{uv(r['sd']):.2f}\t{r['pp']:.0f}\t{100 * r['mains']:.1f}%\t{r['short']:.2f}")
    else:
        r = cal(idx, x)
        p(f"{head}\t{r['periods']}\t{r['a1']:.1f}\t{r['a3']:.1f}\t{r['pp']:.1f}\t{r['resid']:.2f}\t"
          f"{r['step']:.1f}\t{r['codes_per_mv']:.1f}\t{r['codes_per_mv'] / CODES_PER_MV:.3f}")
p(f"# generated {datetime.date.today()} by: ./amplitude_check.py {' '.join(sys.argv[1:])}")
text = "\n".join(out)
print(text)
label = args.label or pathlib.Path(args.files[0]).stem
dest = pathlib.Path("analysis") / f"amplitude_{label}.txt"
dest.parent.mkdir(exist_ok=True)
dest.write_text(text + "\n")
print(f"-> {dest}", file=sys.stderr)
