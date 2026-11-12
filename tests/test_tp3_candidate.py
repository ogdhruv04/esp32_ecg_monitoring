"""The tp3 candidate (tp3_candidate.py): polarity-free timing by alignment. Not shipped."""
import math
import numpy as np
import pan_tompkins as PT
import tp3_candidate as T3
from algorithms import NNSeries, frontend

FS = 256.0


def beat_times(duration_s, seed=0, mean_s=0.85, sd_s=0.03):
    rng = np.random.default_rng(seed)
    t = [1.0]
    while t[-1] < duration_s - 1.5:
        t.append(t[-1] + mean_s + sd_s * rng.standard_normal())
    return np.array(t)


def ecg(t_beats, duration_s, lobes=((0.0, 1.0),), noise=0.01, seed=1, flip_after=None):
    """QRS = sum of Gaussian lobes (offset s, amplitude), sigma 10 ms."""
    n = int(duration_s * FS); ts = np.arange(n) / FS
    x = noise * np.random.default_rng(seed).standard_normal(n)
    for tb in t_beats:
        k0, k1 = max(0, int((tb - 0.3) * FS)), min(n, int((tb + 0.3) * FS))
        s = -1.0 if flip_after is not None and tb > flip_after else 1.0
        for off, amp in lobes:
            x[k0:k1] += s * amp * np.exp(-0.5 * ((ts[k0:k1] - tb - off) / 0.010) ** 2)
    return x


def rr_error_ms(beats, truth):
    """sd of (detected RR - true RR) over unflagged neighbouring beats, after matching to the true beats."""
    pos = np.array([b["pos"] for b in beats]) / FS; fl = np.array([b["flagged"] for b in beats])
    j = np.array([int(np.argmin(np.abs(truth - p))) for p in pos])
    ok = ~fl[:-1] & ~fl[1:] & (np.diff(j) == 1)
    return float(np.std((np.diff(pos) - np.diff(truth[j]))[ok]) * 1000), int(ok.sum())


def test_settings_are_frozen_and_detection_is_untouched():
    assert T3.CONFIG["frozen"] and T3.CONFIG["timing"] == {"LAG": 10, "R_MIN": 0.8, "ALIGN": True, "REF": "peak", "TRACK": 2}
    t = beat_times(60.0); x = ecg(t, 60.0)
    beats = frontend.detect(x, FS)
    b3 = T3.retime(x, beats, FS)
    assert [b["bp"] for b in b3] == [b["bp"] for b in beats] and [b["kind"] for b in b3] == [b["kind"] for b in beats]
    assert beats[20]["pos"] == frontend.detect(x, FS)[20]["pos"]        # retime() does not alter its input


def test_on_a_plain_qrs_it_agrees_with_tp2():
    t = beat_times(120.0); x = ecg(t, 120.0)
    beats = frontend.detect(x, FS); b3 = T3.retime(x, beats, FS)
    late = [i for i, b in enumerate(beats) if b["pos"] > 15 * FS and not b["flagged"] and not b3[i]["flagged"]]
    assert len(late) > 100
    d = np.array([b3[i]["pos"] - beats[i]["pos"] for i in late]) / FS * 1000
    assert abs(np.median(d)) < 1.0 and np.std(d) < 0.5                  # same place: the R peak
    assert rr_error_ms(b3, t)[0] < 0.5 and rr_error_ms(beats, t)[0] < 0.5
    assert np.mean([b["flagged"] for b in b3[12:]]) < 0.02


def test_biphasic_qrs_tp2_flags_everything_tp3_times_it():
    t = beat_times(180.0, seed=3)
    x = ecg(t, 180.0, lobes=((-0.012, 1.0), (0.012, -0.9)))            # two lobes, ratio 1.1: under POL_RATIO
    beats = frontend.detect(x, FS); b3 = T3.retime(x, beats, FS)
    assert np.mean([b["flagged"] for b in beats]) > 0.95               # tp2.1 cannot decide the polarity
    assert np.mean([b["flagged"] for b in b3[12:]]) < 0.03
    assert NNSeries.from_beats(beats, FS).coverage < 0.05 and NNSeries.from_beats(b3, FS).coverage > 0.9
    err, n = rr_error_ms(b3, t)
    assert n > 150 and err < 0.6


def test_absolute_time_does_not_wander_with_the_peak_reference():
    t = beat_times(300.0, seed=5); x = ecg(t, 300.0, noise=0.03)
    beats = frontend.detect(x, FS)

    def offset_sd(cfg):
        b3 = T3.retime(x, beats, FS, cfg)
        pos = np.array([b["pos"] for b in b3 if not b["flagged"]]) / FS
        return float(np.std(pos - t[[int(np.argmin(np.abs(t - p))) for p in pos]]) * 1000)
    assert offset_sd({"REF": "peak"}) < 0.6
    assert offset_sd({"REF": "peak"}) <= offset_sd({"REF": "anchor"}) + 0.05


def test_a_polarity_flip_is_flagged_then_followed():
    t = beat_times(120.0, seed=7); x = ecg(t, 120.0, flip_after=60.0)
    beats = frontend.detect(x, FS); b3 = T3.retime(x, beats, FS)
    pos = np.array([b["pos"] for b in b3]) / FS; fl = np.array([b["flagged"] for b in b3])
    just_after = (pos > 60.0) & (pos < 64.0)
    assert fl[just_after].mean() > 0.6                                  # inverted beats do not match the median beat
    assert fl[pos > 80.0].mean() < 0.05                                 # the median beat has turned over
    err, _ = rr_error_ms([b for b in b3 if b["pos"] / FS > 80.0], t)
    assert err < 0.5


def test_gaps_noise_and_start_are_flagged():
    t = beat_times(60.0, seed=9); x = ecg(t, 60.0)
    beats = frontend.detect(x, FS)
    y = x.copy(); k = int(beats[30]["bp"]); y[k - 3:k + 3] = np.nan     # a hole inside one beat's window
    b3 = T3.retime(y, beats, FS)
    assert b3[30]["flagged"] and math.isfinite(b3[30]["pos"])
    assert all(b["flagged"] for b in b3[:PT.CONFIG["detector"]["POL_MIN"]])   # no median beat yet
    z = x.copy(); z[k - 40:k + 40] += 3.0 * np.random.default_rng(2).standard_normal(80)
    assert T3.retime(z, beats, FS)[30]["flagged"]                        # correlation under R_MIN
