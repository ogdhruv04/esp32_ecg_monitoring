"""Reference implementation of the app's signal-quality gate (SignalQuality.kt).

SignalQualityParityTest requires the phone to give the same numbers and the
same verdict as this on the fixtures make_sqi_fixtures.py writes. If you
change one, change the other. Settings: sqi_config.json (version sqi2).

The gate sees the DISPLAY signal (monitoring filter, then the 0.6 s running
median removed) and the detector's 5-15 Hz signal:

  kSQI   kurtosis of the last 5 s of the display signal. Clean ECG is spiky.
  pSQI   energy of the 5-15 Hz signal / energy of the display signal, same 5 s.
  GOOD   kSQI >= 5 and pSQI >= 0.10;  FAIR  kSQI >= 3.5 and pSQI >= 0.05;
         otherwise POOR.

Kurtosis rewards spikes, so an electrode-settling transient 30 times the size
of a beat scores GOOD on those two alone. The ARTIFACT CHECK (sqi2) looks at
size instead:

  swing      maximum minus minimum of the display signal in one 1 s block
             (blocks are consecutive, counted from the first sample)
  reference  the median swing of the last 30 blocks, the newest included: the
             size of an ordinary second, which is the size of a beat as long
             as most seconds hold one (heart rate above about 30/min)
  artifact   a block whose swing is more than 4 times the reference. The
             verdict is POOR for that block and the 9 after it: the detector's
             thresholds stay upset for a while after a transient. The block
             still being filled counts as soon as its swing so far is more
             than 4 times the last reference.

The median, not a lower percentile: at 45 beats/min a quarter of the seconds
hold no QRS, and a reference taken from those would call every beat an
artifact. The price is that the check goes blind when more than half of the
last 30 s is artifact; the hold covers most of that (analysis/sqi_artifact_dev.txt).

`track` must be given every display sample, in order. Lost samples are simply
not given, as the app's buffers close up over them.
"""
import json, os
import numpy as np

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sqi_config.json")) as _f:
    CONFIG = json.load(_f)
VERSION = CONFIG["version"]
LABELS = {"GOOD": "good contact", "FAIR": "marginal - hold still", "POOR": "too noisy to read",
          "ARTIFACT": "movement artifact - hold still"}


def level_of(k, p, cfg=CONFIG):
    """The verdict from kurtosis and band share alone (the gate before sqi2)."""
    if k >= cfg["k_good"] and p >= cfg["p_good"]:
        return "GOOD"
    if k >= cfg["k_fair"] and p >= cfg["p_fair"]:
        return "FAIR"
    return "POOR"


class SignalQuality:
    def __init__(self, fs=256.0, cfg=None):
        self.cfg = cfg or CONFIG
        a = self.cfg["artifact"]
        self.fs = fs
        self.block = int(a["block_s"] * fs)
        self.memory, self.ratio_max, self.hold_blocks = a["memory_blocks"], a["ratio_max"], a["hold_blocks"]
        self.swings = []            # last `memory` block swings
        self.ratios = []            # swing / reference of the last `hold_blocks` blocks
        self.reference = 0.0        # median swing at the last completed block
        self.hold = 0
        self.count = 0              # samples in the block being filled
        self.lo = self.hi = 0.0

    def track(self, v):
        """One display sample."""
        v = float(v)
        if self.count == 0:
            self.lo = self.hi = v
        else:
            if v < self.lo: self.lo = v
            if v > self.hi: self.hi = v
        self.count += 1
        if self.count < self.block:
            return
        self.count = 0
        swing = self.hi - self.lo
        self.swings.append(swing); self.swings[:] = self.swings[-self.memory:]
        s = sorted(self.swings)
        self.reference = s[(len(s) - 1) // 2]
        flagged = swing > self.ratio_max * self.reference
        self.ratios.append(swing / self.reference if self.reference > 0 else 0.0)
        self.ratios[:] = self.ratios[-self.hold_blocks:]
        if flagged:
            self.hold = self.hold_blocks
        elif self.hold > 0:
            self.hold -= 1

    def artifact_state(self):
        """(artifact now?, largest swing / reference of the last hold_blocks
        blocks and of the block being filled)."""
        ratio = max(self.ratios) if self.ratios else 0.0
        partial = False
        if self.count > 0 and self.reference > 0:
            r = (self.hi - self.lo) / self.reference
            ratio = max(ratio, r)
            partial = (self.hi - self.lo) > self.ratio_max * self.reference
        return self.hold > 0 or partial, ratio

    def assess(self, display, qrs):
        """Verdict over the display window (oldest to newest) and the 5-15 Hz
        signal over the same samples. Returns a dict: level, k, p, artifact,
        ratio, level_kp (the verdict without the artifact check), label."""
        x = np.asarray(display, dtype=float)
        if len(x) < int(self.fs):
            return dict(level="POOR", k=0.0, p=0.0, artifact=False, ratio=0.0, level_kp="POOR", label="waiting for data")
        d = x - x.mean()
        m2 = float(np.mean(d * d)); m4 = float(np.mean(d ** 4))
        k = m4 / (m2 * m2) if m2 > 0 else 0.0
        q = np.asarray(qrs, dtype=float)
        p_tot = float(np.sum(x * x)); p_qrs = float(np.sum(q * q))
        p = min(1.0, max(0.0, p_qrs / p_tot)) if p_tot > 0 else 0.0
        kp = level_of(k, p, self.cfg)
        art, ratio = self.artifact_state()
        level = "POOR" if art else kp
        return dict(level=level, k=k, p=p, artifact=art, ratio=ratio, level_kp=kp,
                    label=LABELS["ARTIFACT"] if art else LABELS[level])


# ---------------------------------------------------------------- the app's chain
BASELINE_S = 0.6            # BaselineRemover.kt
QUALITY_EVERY = 64          # EcgPipeline.kt assesses about 4 times a second


def display_signal(filtered, fs=256.0):
    """BaselineRemover.kt: the filtered signal minus its running median over
    the last 0.6 s (odd length; while the window fills, the median of what
    there is, upper middle). float32 in and out, as on the phone."""
    from scipy.ndimage import median_filter
    f = np.asarray(filtered, dtype=np.float32)
    w = int(fs * BASELINE_S); w += (w % 2 == 0)
    d = f - median_filter(f, size=w, mode="nearest", origin=w // 2)
    for i in range(min(w - 1, len(f))):
        d[i] = f[i] - np.sort(f[:i + 1])[(i + 1) // 2]
    return d.astype(np.float32)


def qrs_signal(filtered, fs=256.0):
    """The detector's 5-15 Hz signal (pan_tompkins biquads), float32."""
    import pan_tompkins as PT
    hp, lp = PT._rbj("hp", 5.0, 0.7071, fs), PT._rbj("lp", 15.0, 0.7071, fs)
    return np.array([lp(hp(float(v))) for v in np.asarray(filtered, dtype=np.float32)], dtype=np.float32)


def replay(filtered, fs=256.0, every=QUALITY_EVERY, cfg=None):
    """Run the gate over a filtered recording the way EcgPipeline does: 5 s
    buffers, one verdict every `every` samples once 1 s has arrived. Returns
    (sample count at each verdict, list of assess() dicts). The filter itself
    is the caller's; scipy's Butterworth chain approximates EcgFilter.kt."""
    d, q = display_signal(filtered, fs), qrs_signal(filtered, fs)
    sq = SignalQuality(fs, cfg)
    w = int((cfg or CONFIG)["window_s"] * fs)
    at, out = [], []
    for i in range(len(d)):
        sq.track(d[i])
        n = i + 1
        if n % every == 0 and n >= int(fs):
            at.append(n); out.append(sq.assess(d[max(0, n - w):n], q[max(0, n - w):n]))
    return np.array(at), out
