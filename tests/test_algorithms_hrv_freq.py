"""Lomb-Scargle LF/HF: against scipy, against known sinusoids, and the minimum window."""
import math
import numpy as np
import pytest
from scipy import signal as sps
from algorithms import NNSeries, frequency_domain, lomb_scargle


def modulated_beats(duration_s, mean_ms=1000.0, comps=((0.10, 30.0), (0.25, 20.0))):
    """Beat times whose NN interval is mean + sum of A*sin(2 pi f t)."""
    t = [0.0]
    while t[-1] < duration_s:
        nn = mean_ms + sum(a * math.sin(2 * math.pi * f * t[-1]) for f, a in comps)
        t.append(t[-1] + nn / 1000.0)
    return np.array(t)


def test_periodogram_matches_scipy():
    rng = np.random.default_rng(3)
    t = np.sort(rng.uniform(0, 300, 280)); y = rng.standard_normal(280); y -= y.mean()
    f = np.linspace(0.04, 0.4, 200)
    assert np.allclose(lomb_scargle(t, y, f), sps.lombscargle(t, y, 2 * np.pi * f), rtol=1e-9, atol=1e-12)


def test_periodogram_matches_astropy_which_neurokit_uses():
    ats = pytest.importorskip("astropy.timeseries")
    rng = np.random.default_rng(3)
    t = np.sort(rng.uniform(0, 300, 280)); y = rng.standard_normal(280); y -= y.mean()
    f = np.linspace(0.04, 0.4, 200)
    ref = ats.LombScargle(t, y, normalization="psd", fit_mean=False, center_data=False).power(f)
    assert np.allclose(lomb_scargle(t, y, f), ref, rtol=1e-9, atol=1e-12)


def test_band_power_of_known_sinusoids():
    nn = NNSeries.from_times(modulated_beats(300.0), clean=False)
    r = frequency_domain(nn)
    assert abs(r["lf"].value - 30.0 ** 2 / 2) / 450.0 < 0.05       # A^2/2 = 450 ms^2
    assert abs(r["hf"].value - 20.0 ** 2 / 2) / 200.0 < 0.05       # 200 ms^2
    assert abs(r["lf_hf"].value - 2.25) / 2.25 < 0.05
    assert abs(r["lf_nu"].value - 100 * 450 / 650) < 2.0
    assert r["lf"].unit == "ms^2" and r["lf_hf"].n_used == nn.n_accepted


def test_band_power_with_a_few_missing_beats():
    t = modulated_beats(300.0)
    f = np.zeros(len(t), bool); f[[40, 111, 173, 250]] = True       # 8 of ~300 intervals lost
    nn = NNSeries.from_times(t, flagged=f, clean=False)
    assert 0.95 < nn.coverage < 0.99
    r = frequency_domain(nn)
    assert abs(r["lf"].value - 450.0) / 450.0 < 0.10
    assert abs(r["hf"].value - 200.0) / 200.0 < 0.10
    assert abs(r["lf_hf"].value - 2.25) / 2.25 < 0.10


def test_spectral_measures_withheld_below_95_percent_coverage():
    t = modulated_beats(300.0)
    f = np.random.default_rng(4).random(len(t)) < 0.10              # ~19% of intervals lost
    nn = NNSeries.from_times(t, flagged=f, clean=False)
    assert 0.75 < nn.coverage < 0.90 and nn.valid_s > 200
    r = frequency_domain(nn)
    assert all(v.value is None for v in r.values())
    assert "coverage" in r["hf"].withheld and "needs 95%" in r["lf"].withheld


def test_power_stays_in_its_own_band():
    lf_only = frequency_domain(NNSeries.from_times(modulated_beats(300.0, comps=((0.10, 30.0),)), clean=False))
    assert lf_only["hf"].value < 0.03 * lf_only["lf"].value
    hf_only = frequency_domain(NNSeries.from_times(modulated_beats(300.0, comps=((0.25, 20.0),)), clean=False))
    assert hf_only["lf"].value < 0.03 * hf_only["hf"].value


def test_minimum_windows_lf_120s_hf_60s():
    r = frequency_domain(NNSeries.from_times(modulated_beats(50.0), clean=False))
    assert all(v.value is None for v in r.values())
    r = frequency_domain(NNSeries.from_times(modulated_beats(100.0), clean=False))
    assert r["hf"].ok and r["lf"].value is None and "120 s" in r["lf"].withheld
    assert r["lf_hf"].value is None and r["lf_nu"].value is None      # a ratio needs both
    r = frequency_domain(NNSeries.from_times(modulated_beats(125.0), clean=False))
    assert all(v.ok for v in r.values())


def test_hf_withheld_when_the_heart_is_too_slow_to_sample_it():
    r = frequency_domain(NNSeries.from_times(modulated_beats(300.0, mean_ms=1300.0), clean=False))
    assert r["lf"].ok and r["hf"].value is None and "beat rate" in r["hf"].withheld
    assert r["lf_hf"].value is None
