#!/usr/bin/env python3
"""Finger-vs-chest agreement from a capture_dual.py recording.

    ./agreement.py captures/20260929_1200_dual01_ring.csv captures/20260929_1200_dual01_ref.csv

The chest recording is the reference; the ring (finger) is the device under
test. Both boards run the same firmware at the same rate, so the only
difference is electrode site - that is the whole point of the experiment.

Reports, in this order:
  1. integrity of each stream  (nothing below it means anything if this fails)
  2. clock alignment           (offset and drift between the two boards)
  3. beat agreement            (Se / P+ of finger beats against chest beats)
  4. heart-rate agreement      (Bland-Altman bias and limits, ICC, CCC)
  5. RR-interval agreement     (the quantity every HRV number is built on)

Timing comes from the sample index, not the host clock: sample N was taken at
N/256 s by each board's own oscillator (see CLAUDE.md). The two boards have no
shared clock, so the constant offset between them is estimated from the beat
trains themselves. RR intervals are differences, so a constant offset cancels
in sections 4 and 5 - it only matters for matching individual beats in 3.
"""
import argparse, pathlib, sys
import numpy as np
from scipy import signal as sps
import pan_tompkins

ap = argparse.ArgumentParser()
ap.add_argument("ring", help="CSV from the finger/ring device")
ap.add_argument("ref", help="CSV from the chest/reference device")
ap.add_argument("--fs", type=float, default=256.0)
ap.add_argument("--mains", type=float, default=50.0)
ap.add_argument("--window", type=float, default=10.0, help="seconds per heart-rate window")
ap.add_argument("--tol-ms", type=float, default=150.0, help="beat matching tolerance (EC57 uses 150 ms)")
ap.add_argument("--max-offset", type=float, default=5.0,
                help="seconds of offset to search around the host-clock alignment")
ap.add_argument("--skip-s", type=float, default=10.0,
                help="discard this many seconds at the start: electrodes settling after attachment "
                     "produce a transient that poisons the detector's adaptive threshold")
ap.add_argument("--plot", action="store_true")
args = ap.parse_args()

FS, TOL = args.fs, args.tol_ms / 1000.0

# ----------------------------------------------------------------- load
def load(path):
    """Read a capture, keep the longest gap-free run, and report integrity.

    Filtering assumes evenly spaced samples, so a run with dropped samples
    cannot simply be concatenated - the gap would become a step that the
    filters ring on and the detector reads as a beat. We analyse the longest
    clean stretch instead, and say how much was discarded.
    """
    raw = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                        invalid_raise=False)
    idx = raw["index"].astype(np.int64)
    val = raw["value"].astype(float)
    etag = raw["etag"].astype(np.int64)

    # Drop the settling period. Attaching an electrode produces a step far
    # larger than any R-peak; Pan-Tompkins learns its threshold from the start
    # of the signal and cannot recover from one, so it must not see it.
    skip = int(args.skip_s * FS)
    if skip and len(idx) > skip * 2:
        idx, val, etag = idx[skip:], val[skip:], etag[skip:]

    # ETAG 1 and 3 are fast-recovery samples: the time step is valid but the
    # voltage is not (datasheet Rev 3 p.42), so they must not reach the filter.
    bad_etag = int(np.sum(np.isin(etag, [1, 3])))
    dups = int(np.sum(np.diff(idx) == 0))

    # Split wherever the index is not exactly +1: a gap, a duplicate, or a
    # device reset (index jumps backwards).
    breaks = np.flatnonzero(np.diff(idx) != 1) + 1
    runs = np.split(np.arange(len(idx)), breaks)
    keep = max(runs, key=len)
    span = idx[-1] - idx[0] + 1
    missing = span - len(idx)

    host = raw["host_time"].astype(float) if "host_time" in (raw.dtype.names or ()) else None
    return dict(path=pathlib.Path(path).name, idx=idx[keep], val=val[keep],
                host0=(float(host[keep][0]) if host is not None else None),
                n=len(idx), span=span, missing=missing, gaps=len(breaks),
                dups=dups, bad_etag=bad_etag, kept=len(keep))

def filter_chain(x, fs, mains):
    """Zero-phase 0.5-40 Hz with a mains notch - offline, so no phase lag."""
    y = sps.sosfiltfilt(sps.butter(4, 0.5, "highpass", fs=fs, output="sos"), x)
    b, a = sps.iirnotch(mains, 30.0, fs=fs); y = sps.filtfilt(b, a, y)
    if mains * 2 < fs / 2:
        b, a = sps.iirnotch(mains * 2, 30.0, fs=fs); y = sps.filtfilt(b, a, y)
    return sps.sosfiltfilt(sps.butter(4, 40.0, "lowpass", fs=fs, output="sos"), y)

# ----------------------------------------------------------------- stats
def bland_altman(a, b):
    """a - b, with the 95% limits of agreement. Bias alone hides the spread."""
    d = a - b
    bias, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    return bias, sd, bias - 1.96 * sd, bias + 1.96 * sd

def lins_ccc(a, b):
    """Concordance: penalises both scatter AND systematic offset, unlike r."""
    va, vb = np.var(a), np.var(b)
    cov = np.mean((a - a.mean()) * (b - b.mean()))
    return float(2 * cov / (va + vb + (a.mean() - b.mean()) ** 2))

def icc21(a, b):
    """ICC(2,1): two-way random effects, absolute agreement, single measure."""
    m = np.column_stack([a, b]).astype(float)
    n, k = m.shape
    gm = m.mean()
    msr = k * np.sum((m.mean(axis=1) - gm) ** 2) / (n - 1)          # between windows
    msc = n * np.sum((m.mean(axis=0) - gm) ** 2) / (k - 1)          # between devices
    sse = np.sum((m - m.mean(axis=1, keepdims=True) - m.mean(axis=0, keepdims=True) + gm) ** 2)
    mse = sse / ((n - 1) * (k - 1))
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    return float((msr - mse) / denom) if denom else float("nan")

# ----------------------------------------------------------------- run
ring, ref = load(args.ring), load(args.ref)
print(f"\nfinger-vs-chest agreement   tolerance {args.tol_ms:g} ms   {args.window:g} s windows\n")
print("1. integrity")
for d, name in ((ref, "chest (reference)"), (ring, "finger (ring)")):
    print(f"   {name:18} {d['path']}")
    print(f"   {'':18} {d['n']} samples, {d['missing']} missing ({100*d['missing']/d['span']:.2f}%), "
          f"{d['gaps']} gaps, {d['dups']} duplicate idx, {d['bad_etag']} fast-mode")
    print(f"   {'':18} longest clean run {d['kept']} samples = {d['kept']/FS:.1f} s"
          f" ({100*d['kept']/d['n']:.1f}% of what arrived)")
    if d["kept"] < 30 * FS:
        sys.exit(f"\nABORT: {name} has under 30 s of clean data - fix capture before analysing")

beats = {}
for key, d in (("ref", ref), ("ring", ring)):
    y = filter_chain(d["val"], FS, args.mains)
    peaks = pan_tompkins.detect(y, FS)
    # Absolute time on that board's own clock: sample index / rate.
    # Each board's sample index starts at its own power-on, so index/FS gives
    # two clocks minutes apart. capture_dual.py stamps every sample with the
    # host time, which is coarse (tens of ms) but shares an origin - use it for
    # the offset, and let the beat trains refine from there.
    beats[key] = (d["host0"] if d["host0"] is not None else d["idx"][0] / FS) + peaks / FS
    d["filt"], d["peaks"] = y, peaks
print(f"\n   beats detected: chest {len(beats['ref'])}, finger {len(beats['ring'])}")

# ---- 2. alignment: the boards share no clock, so recover the offset from the
# beat trains. Coarse cross-correlation of binned impulse trains, then refine
# on the median of matched differences.
BIN = 0.01
t0 = min(beats["ref"][0], beats["ring"][0])
span = max(beats["ref"][-1], beats["ring"][-1]) - t0
nb = int(span / BIN) + 1
def train(t):
    v = np.zeros(nb + 1)
    v[((t - t0) / BIN).astype(int)] = 1.0
    return v
xc = sps.correlate(train(beats["ring"]), train(beats["ref"]), mode="full")
lags = sps.correlation_lags(nb + 1, nb + 1, mode="full") * BIN
sel = np.abs(lags) <= args.max_offset
offset = float(lags[sel][np.argmax(xc[sel])])      # ring time - chest time

def align(offset, drift_ppm=0.0):
    r = beats["ring"] - offset
    return r - (r - r[0]) * drift_ppm * 1e-6

def match(offset, drift_ppm=0.0, clip=False):
    """Greedy nearest matching of finger beats to chest beats, each used once.

    With clip=True, both trains are cut to the time span the two recordings
    share. Without it, any difference in length (one device started later, or
    lost a stretch to a gap) counts as missed beats and destroys sensitivity -
    it scored 65% instead of 99% on a self-test before this was added.
    """
    r = align(offset, drift_ppm)
    ref_t = beats["ref"]
    if clip:
        lo, hi = max(ref_t[0], r[0]), min(ref_t[-1], r[-1])
        r = r[(r >= lo) & (r <= hi)]
        ref_t = ref_t[(ref_t >= lo) & (ref_t <= hi)]
    used = np.zeros(len(ref_t), bool)
    pairs = []
    for t in r:
        i = np.searchsorted(ref_t, t)
        best, bd = -1, TOL + 1
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(ref_t) and not used[j] and abs(ref_t[j] - t) < bd:
                best, bd = j, abs(ref_t[j] - t)
        if best >= 0 and bd <= TOL:
            used[best] = True
            pairs.append((best, t, ref_t[best]))
    return pairs, used, ref_t, r

for _ in range(3):                                  # refine the offset estimate
    pairs, *_ = match(offset)
    if not pairs:
        break
    offset += float(np.median([t - rt for _, t, rt in pairs]))

pairs, *_ = match(offset)
drift_ppm = 0.0
drift_se_ppm = float("nan")
if len(pairs) > 20:
    tt = np.array([rt for _, _, rt in pairs]); dd = np.array([t - rt for _, t, rt in pairs])
    slope, icept = np.polyfit(tt - tt[0], dd, 1)
    resid = dd - (slope * (tt - tt[0]) + icept)
    # Standard error of the slope: tells us whether the drift is real or fit noise.
    sx = np.sum((tt - tt[0] - np.mean(tt - tt[0])) ** 2)
    drift_se_ppm = float(np.std(resid, ddof=2) / np.sqrt(sx) * 1e6) if sx > 0 else float("nan")
    drift_ppm = slope * 1e6
print("\n2. clock alignment")
print(f"   offset (finger - chest)  {offset*1000:+.0f} ms")
print(f"   relative drift           {drift_ppm:+.1f} +/- {drift_se_ppm:.1f} ppm "
      f"({abs(drift_ppm)*1e-6*span*1000:.1f} ms over {span/60:.1f} min)")
if abs(drift_ppm) < 2 * drift_se_ppm:
    print("   (drift is within its own uncertainty - consistent with no measurable drift)")

# ---- 3. beat agreement, chest as reference
pairs, used, ref_c, ring_c = match(offset, drift_ppm, clip=True)
if len(ref_c) == 0 or len(ring_c) == 0:
    sys.exit(f"\nABORT: no overlap after alignment (offset {offset:+.1f} s). The two recordings do not "
             f"cover a common period, or the offset search failed - check --max-offset.")
tp = len(pairs)
fn = int(np.sum(~used))
fp = len(ring_c) - tp
se = 100.0 * tp / (tp + fn) if tp + fn else 0.0
pp = 100.0 * tp / (tp + fp) if tp + fp else 0.0
print("\n3. beat agreement (chest beats are the reference)")
print(f"   over the {ref_c[-1]-ref_c[0]:.0f} s both recordings share: "
      f"chest {len(ref_c)} beats, finger {len(ring_c)}")
print(f"   matched {tp}   missed {fn}   extra {fp}")
print(f"   Se {se:.2f}%   P+ {pp:.2f}%")

# ---- 4. heart rate per window
edges = np.arange(max(beats["ref"][0], beats["ring"][0] - offset),
                  min(beats["ref"][-1], beats["ring"][-1] - offset), args.window)
hr_ref, hr_ring = [], []
ring_aligned = beats["ring"] - offset
for e in edges[:-1]:
    for src, out in ((beats["ref"], hr_ref), (ring_aligned, hr_ring)):
        w = src[(src >= e) & (src < e + args.window)]
        # Median, not mean: one missed beat doubles a single RR interval and
        # would shift a mean-based HR by several bpm. Missed beats are already
        # reported honestly as sensitivity in section 3; letting them corrupt
        # the HR too would count the same failure twice.
        out.append(60.0 / np.median(np.diff(w)) if len(w) >= 3 else np.nan)
hr_ref, hr_ring = np.array(hr_ref), np.array(hr_ring)
ok = ~(np.isnan(hr_ref) | np.isnan(hr_ring))
print(f"\n4. heart rate, {int(ok.sum())} windows of {args.window:g} s "
      f"({int((~ok).sum())} dropped for too few beats)")
if ok.sum() >= 3:
    bias, sd, lo, hi = bland_altman(hr_ring[ok], hr_ref[ok])
    print(f"   chest {np.mean(hr_ref[ok]):.1f} bpm   finger {np.mean(hr_ring[ok]):.1f} bpm")
    print(f"   bias {bias:+.2f} bpm   limits of agreement {lo:+.2f} to {hi:+.2f} bpm")
    print(f"   ICC(2,1) {icc21(hr_ring[ok], hr_ref[ok]):.4f}   Lin CCC {lins_ccc(hr_ring[ok], hr_ref[ok]):.4f}"
          f"   Pearson r {np.corrcoef(hr_ring[ok], hr_ref[ok])[0,1]:.4f}")
    print("   (r alone is not enough: two series can correlate perfectly and still be offset)")
else:
    print("   too few usable windows")

# ---- 5. RR intervals on matched beats
rr_saved = None
print("\n5. RR intervals (matched beats only)")
if len(pairs) > 3:
    ref_i = np.array([p[0] for p in pairs])
    rr_ref = np.diff(ref_c[ref_i]) * 1000
    rr_ring = np.diff(np.array([p[1] for p in pairs])) * 1000
    # Only consecutive matches: a skipped beat would fake a huge interval.
    consec = np.diff(ref_i) == 1
    rr_ref, rr_ring = rr_ref[consec], rr_ring[consec]
    if len(rr_ref) > 3:
        bias, sd, lo, hi = bland_altman(rr_ring, rr_ref)
        print(f"   {len(rr_ref)} intervals   bias {bias:+.2f} ms   limits {lo:+.2f} to {hi:+.2f} ms")
        rm_ref = float(np.sqrt(np.mean(np.diff(rr_ref)**2)))
        rm_ring = float(np.sqrt(np.mean(np.diff(rr_ring)**2)))
        print(f"   RMSSD chest {rm_ref:.1f} ms   finger {rm_ring:.1f} ms")
        rr_saved = (len(rr_ref), bias, lo, hi, rm_ref, rm_ring)
    else:
        print("   too few consecutive matched pairs")
else:
    print("   too few matched beats")

# ---- save
outdir = pathlib.Path("analysis"); outdir.mkdir(exist_ok=True)
stem = pathlib.Path(args.ring).stem.replace("_ring", "")
rep = outdir / f"agreement_{stem}.txt"
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(f"source: {args.ring} + {args.ref}")
    # Record the settings too. The offset depends on --skip-s (a report saved
    # without it once read +131 ms where the default gives -16 ms), so a report
    # that omits them cannot be reproduced from itself.
    print(f"settings: fs={args.fs:g} mains={args.mains:g} window={args.window:g}s "
          f"tol={args.tol_ms:g}ms skip={args.skip_s:g}s max_offset={args.max_offset:g}s")
    print(f"offset {offset*1000:+.0f} ms, drift {drift_ppm:+.1f} +/- {drift_se_ppm:.1f} ppm")
    print(f"beats matched {tp} missed {fn} extra {fp}  Se {se:.2f}%  P+ {pp:.2f}%")
    if ok.sum() >= 3:
        bias, sd, lo, hi = bland_altman(hr_ring[ok], hr_ref[ok])
        print(f"HR bias {bias:+.2f} bpm  LoA {lo:+.2f}..{hi:+.2f}  ICC {icc21(hr_ring[ok], hr_ref[ok]):.4f}"
              f"  CCC {lins_ccc(hr_ring[ok], hr_ref[ok]):.4f}")
    if rr_saved is not None:
        n_rr, rb, rlo, rhi, rm_ref, rm_ring = rr_saved
        print(f"RR {n_rr} intervals  bias {rb:+.2f} ms  LoA {rlo:+.2f}..{rhi:+.2f}"
              f"  RMSSD chest {rm_ref:.1f} ms  finger {rm_ring:.1f} ms")
rep.write_text(buf.getvalue())
print(f"\nsaved {rep}")

if args.plot:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(11, 10))
    n = int(10 * FS)
    ax[0].plot(np.arange(n) / FS, ref["filt"][:n], lw=.8, label="chest")
    ax[0].plot(np.arange(n) / FS, ring["filt"][:n] , lw=.8, alpha=.75, label="finger")
    ax[0].set_title("first 10 s, filtered (not time-aligned)"); ax[0].legend(); ax[0].set_xlabel("s")
    if ok.sum() >= 3:
        m = (hr_ring[ok] + hr_ref[ok]) / 2; d = hr_ring[ok] - hr_ref[ok]
        bias, sd, lo, hi = bland_altman(hr_ring[ok], hr_ref[ok])
        ax[1].scatter(m, d, s=14)
        for y, ls in ((bias, "-"), (lo, "--"), (hi, "--")):
            ax[1].axhline(y, ls=ls, lw=1)
        ax[1].set_title("Bland-Altman, heart rate"); ax[1].set_xlabel("mean bpm"); ax[1].set_ylabel("finger - chest")
        ax[2].scatter(hr_ref[ok], hr_ring[ok], s=14)
        lim = [min(hr_ref[ok].min(), hr_ring[ok].min()) - 2, max(hr_ref[ok].max(), hr_ring[ok].max()) + 2]
        ax[2].plot(lim, lim, lw=1); ax[2].set_xlabel("chest bpm"); ax[2].set_ylabel("finger bpm")
        ax[2].set_title("identity line")
    fig.tight_layout()
    png = str(rep).replace(".txt", ".png")
    fig.savefig(png, dpi=110)
    print(f"saved {png}")
