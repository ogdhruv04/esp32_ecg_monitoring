"""Pulse detection, skin-conductance decomposition and temperature slope
(docs/wesad_plan.md, section 4), on synthetic signals with known answers."""
import math
import numpy as np
import pytest
from algorithms import ppg, eda, temp

FS = 64.0


def pulse_train(beat_t, fs=FS, dur=None, amp=None, width=0.09):
    dur = dur or beat_t[-1] + 2.0
    t = np.arange(int(dur * fs)) / fs
    amp = np.ones(len(beat_t)) if amp is None else amp
    x = np.zeros(len(t))
    for b, a in zip(beat_t, amp):
        x += a * np.exp(-0.5 * ((t - b) / width) ** 2) + 0.3 * a * np.exp(-0.5 * ((t - b - 0.3) / 0.1) ** 2)
    return x


def beats(n=200, seed=0, mean=0.85, sd=0.04):
    return 1.0 + np.cumsum(mean + sd * np.random.default_rng(seed).standard_normal(n))


# ------------------------------------------------------------------- PPG
def test_finds_every_pulse_and_interpolates_between_samples():
    bt = beats()
    p = ppg.detect(ppg.bandpass(pulse_train(bt), FS), FS)
    assert len(p) == len(bt)
    err = p.t - bt
    err -= np.median(err)                       # a constant offset is not a timing error
    assert np.std(err) < 0.002                  # the 64 Hz grid alone would give 4.5 ms
    assert np.std(np.diff(p.t) - np.diff(bt)) < 0.003
    assert np.all(np.diff(p.index) > 0)


def test_dicrotic_wave_is_not_a_second_pulse():
    bt = 1.0 + np.arange(60) * 1.0              # slow heart: the second bump is 0.3 s after the peak
    p = ppg.detect(ppg.bandpass(pulse_train(bt), FS), FS)
    assert len(p) == 60 and np.all(np.abs(np.diff(p.t) - 1.0) < 0.01)


def test_agrees_with_neurokit2_on_the_same_filtered_signal():
    nk = pytest.importorskip("neurokit2")
    x = nk.ppg_simulate(duration=120, sampling_rate=int(FS), heart_rate=72, random_state=3)
    y = ppg.bandpass(x, FS)
    theirs = nk.ppg_findpeaks(y, sampling_rate=int(FS), method="elgendi")["PPG_Peaks"]
    ours = ppg.detect(y, FS).index
    assert abs(len(ours) - len(theirs)) <= 1
    near = [np.min(np.abs(theirs - k)) for k in ours]
    assert np.mean(np.array(near) <= 1) > 0.98


def test_amplitude_follows_the_pulse_size():
    bt = beats(240)
    amp = np.where(np.arange(240) < 120, 1.0, 0.5)
    p = ppg.detect(ppg.bandpass(pulse_train(bt, amp=amp), FS), FS)
    a, b = np.median(p.amp[10:110]), np.median(p.amp[130:230])
    assert math.isclose(a / b, 2.0, rel_tol=0.05)


def test_window_features_and_their_minimums():
    bt = beats(400)
    p = ppg.detect(ppg.bandpass(pulse_train(bt), FS), FS)
    nn = ppg.pulse_intervals(p)
    v, info = ppg.window_features(p, nn, 10.0, 190.0)
    assert math.isclose(v["pr"], 60.0 / np.median(np.diff(bt[(bt >= 10) & (bt < 190)])), rel_tol=0.01)
    assert all(np.isfinite(list(v.values()))) and info["coverage"] > 0.95
    assert math.isclose(math.exp(v["ln_rmssd_p"]), 1000 * np.sqrt(np.mean(np.diff(np.diff(bt[(bt >= 10) & (bt < 190)])) ** 2)), rel_tol=0.1)
    short, _ = ppg.window_features(p, nn, 10.0, 40.0)        # about 35 pulses
    assert all(np.isnan(list(short.values())))


def test_noise_bursts_lose_coverage_rather_than_invent_variability():
    bt = beats(300)
    x = pulse_train(bt)
    rng = np.random.default_rng(5)
    k = (np.arange(len(x)) / FS > 100) & (np.arange(len(x)) / FS < 160)
    x[k] += 2.0 * rng.standard_normal(k.sum())
    p = ppg.detect(ppg.bandpass(x, FS), FS)
    nn = ppg.pulse_intervals(p)
    assert nn.window(100, 160).coverage < 0.8 and nn.window(10, 90).coverage > 0.95


# ------------------------------------------------------------------- EDA
def eda_signal(scr_t, scr_amp, dur=600.0, fs=4.0, level=3.0, drift=0.001, noise=0.0005, seed=0):
    t = np.arange(int(dur * fs)) / fs
    x = level + drift * t + noise * np.random.default_rng(seed).standard_normal(len(t))
    for t0, a in zip(scr_t, np.broadcast_to(scr_amp, len(scr_t))):
        d = np.clip(t - t0, 0, None)
        bate = np.exp(-d / 2.0) - np.exp(-d / 0.7)
        x += a * bate / 0.31                    # 0.31 is the Bateman function's maximum for these constants
    return x


def test_resampling_has_no_edge_transient():
    x = np.full(700 * 60, 5.0)
    y = eda.to_rate(x, 700.0)
    assert len(y) == 240 and np.allclose(y, 5.0, atol=1e-6)
    ramp = 30.0 + np.arange(700 * 60) / 700.0 / 60.0
    assert np.allclose(eda.to_rate(ramp, 700.0), 30.0 + np.arange(240) / 4.0 / 60.0, atol=1e-3)


def test_counts_the_planted_responses():
    scr_t = np.arange(30.0, 570.0, 45.0)
    x = eda_signal(scr_t, 0.3)
    d = eda.decompose(x)
    assert len(d.peaks) == len(scr_t)
    assert np.all(np.abs(d.peaks / 4.0 - (scr_t + 1.4)) < 1.5)       # a response peaks about 1.4 s after its onset
    assert d.phasic.min() > -0.005                                    # its driver is non-negative; the component nearly so
    assert np.max(np.abs(d.tonic + d.phasic - x)) < 0.05


def test_decomposition_scales_with_the_signal():
    x = eda_signal(np.arange(30.0, 570.0, 45.0), 0.3)
    a, b = eda.decompose(x), eda.decompose(2 * x)
    assert np.allclose(b.phasic, 2 * a.phasic, atol=1e-4) and np.allclose(b.tonic, 2 * a.tonic, atol=1e-4)


def test_threshold_decides_what_counts_as_a_response():
    x = eda_signal(np.arange(30.0, 570.0, 45.0), 0.03)
    assert len(eda.decompose(x).peaks) == 12
    assert len(eda.decompose(x, min_us=0.05).peaks) == 0


def test_eda_window_features():
    scr_t = np.arange(30.0, 570.0, 45.0)
    x = eda_signal(scr_t, 0.3, drift=0.002)
    d = eda.decompose(x)
    v = eda.window_features(x, d, 200.0, 380.0)
    assert math.isclose(v["scr_rate"], np.sum((scr_t + 1.4 >= 200) & (scr_t + 1.4 < 380)) / 3.0)
    assert math.isclose(v["scl_slope"], 0.12, abs_tol=0.03)          # 0.002 uS/s
    assert 3.0 < v["scl"] < 4.5 and v["phasic_mean"] > 0
    x0 = x.copy(); x0[1000] = 0.0                                    # contact lost at 250 s
    assert all(np.isnan(list(eda.window_features(x0, d, 200.0, 380.0).values())))
    assert all(np.isfinite(list(eda.window_features(x0, d, 300.0, 480.0).values())))


def test_flat_signal_has_no_responses():
    d = eda.decompose(np.full(2400, 2.0))
    assert len(d.peaks) == 0 and np.all(d.phasic == 0)


# ------------------------------------------------------------------ TEMP
def test_temperature_slope_and_when_it_is_withheld():
    t = np.arange(4 * 600) / 4.0
    x = 32.0 + 0.05 * t / 60.0
    assert math.isclose(temp.slope(x, 100.0, 280.0), 0.05, rel_tol=1e-6)
    off = x.copy(); off[500:520] = 18.0                              # sensor off the skin at 125-130 s
    assert math.isnan(temp.slope(off, 100.0, 280.0)) and math.isfinite(temp.slope(off, 200.0, 380.0))
    bad = x.copy(); bad[900] = np.nan
    assert math.isnan(temp.slope(bad, 100.0, 280.0))
    assert math.isnan(temp.slope(x, 500.0, 680.0))                   # runs past the end
