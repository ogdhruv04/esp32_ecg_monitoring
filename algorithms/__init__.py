"""Algorithms on top of the tp2.1 beat detector: HRV and ECG-derived breathing rate.

    from algorithms import NNSeries, hrv, breathing_rate, modulations
    nn = NNSeries.from_beats(detector.beats, fs).window(t0, t1)
    for r in hrv(nn).values(): print(r)        # each a Result; value None = withheld

Every measure has a minimum valid window (config.json, docs/hrv_minimum_windows.md)
and returns no value below it. Parameters are frozen in algorithms/config.json.
"""
from .core import CONFIG, VERSION, NNSeries, Result, gate, minimum
from .hrv_time import rmssd, sdnn, pnn50, time_domain
from .hrv_freq import frequency_domain, lomb_scargle
from .hrv_nonlinear import poincare, dfa_alpha1, sample_entropy, nonlinear
from .breathing import Modulations, modulations, r_amplitudes, breathing_rate, window_spectra, rate_from_spectra


def hrv(nn):
    """Every HRV measure of one NNSeries window: name -> Result."""
    return {**time_domain(nn), **frequency_domain(nn), **nonlinear(nn)}
