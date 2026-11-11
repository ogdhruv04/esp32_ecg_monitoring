"""RMSSD, SDNN, pNN50: values, holes, and the minimum window."""
import math
import numpy as np
import pan_tompkins as PT
from algorithms import NNSeries, rmssd, sdnn, pnn50, time_domain


def test_known_values():
    nn = NNSeries.from_intervals([800.0, 860.0] * 100)        # 166 s, differences all +-60 ms
    assert math.isclose(rmssd(nn).value, 60.0)
    assert math.isclose(sdnn(nn).value, np.std([800.0, 860.0] * 100, ddof=1))
    assert math.isclose(pnn50(nn).value, 100.0)
    nn = NNSeries.from_intervals([800.0, 850.0] * 100)        # exactly 50 ms is not "more than 50"
    assert math.isclose(rmssd(nn).value, 50.0) and pnn50(nn).value == 0.0


def test_pnn50_counts_differences_over_50ms():
    rr = [800.0] * 150
    for i in range(10, 150, 10):
        rr[i] = 870.0                                         # 14 spikes: 28 of 149 differences
    r = pnn50(NNSeries.from_intervals(rr))
    assert r.n_used == 149 and math.isclose(r.value, 100.0 * 28 / 149)


def test_rmssd_is_the_detectors_rmssd():
    rng = np.random.default_rng(2)
    rr = list(800.0 + 30.0 * rng.standard_normal(250))
    for i in (40, 41, 100, 180):
        rr[i] = math.nan
    rr[60] = 1500.0                                           # dropped by the 20% rule
    ref, n_acc, _, cov = PT.rmssd_nn(rr)
    t = np.concatenate([[0.0], np.cumsum(np.nan_to_num(np.array(rr), nan=800.0)) / 1000.0])
    acc, _ = PT.clean_nn(rr)
    nn = NNSeries(t, np.where(acc, np.array(rr), np.nan))
    r = rmssd(nn)
    assert abs(r.value - ref) < 1e-9 and nn.n_accepted == n_acc and math.isclose(r.coverage, cov)


def test_no_difference_is_taken_across_a_hole():
    t = np.concatenate([np.arange(0, 100) * 0.8, 80.0 + np.arange(0, 100) * 1.0])
    f = np.zeros(200, bool); f[100] = True                    # the beat where the rate steps
    nn = NNSeries.from_times(t, flagged=f, clean=False)
    assert math.isclose(rmssd(nn).value, 0.0, abs_tol=1e-9)   # 800 -> 1000 ms step never differenced
    assert pnn50(nn).value == 0.0
    assert sdnn(nn).value > 90.0                              # SDNN does see both levels


def test_values_are_withheld_below_the_minimum_window():
    short = NNSeries.from_intervals([800.0, 830.0] * 36)      # 58.7 s
    for r in (rmssd(short), pnn50(short), sdnn(short)):
        assert r.value is None and not r.ok and "needs" in r.withheld
    mid = NNSeries.from_intervals([800.0, 830.0] * 40)        # 65.2 s
    assert rmssd(mid).ok and pnn50(mid).ok
    assert sdnn(mid).value is None and "120 s" in sdnn(mid).withheld
    long = NNSeries.from_intervals([800.0, 830.0] * 75)       # 122 s
    assert all(r.ok for r in time_domain(long).values())


def test_fast_heart_still_needs_the_time_and_slow_heart_the_count():
    fast = NNSeries.from_intervals([400.0] * 100)             # 100 intervals but 40 s
    assert rmssd(fast).value is None and "60 s" in rmssd(fast).withheld
    assert PT.rmssd_nn([400.0] * 100)[0] is not None          # the count-only rule would report
    slow = NNSeries.from_intervals([1900.0] * 32)             # 60.8 s, 32 intervals
    assert rmssd(slow).ok
    hole = np.zeros(34, bool); hole[::8] = True               # leaves < 30 accepted intervals
    few = NNSeries.from_times(np.arange(34) * 3.0, flagged=hole, clean=False)
    assert few.valid_s >= 60 and few.n_accepted < 30 and "accepted NN" in rmssd(few).withheld


def test_result_carries_coverage_and_duration():
    t = np.arange(0, 201) * 0.9
    f = np.zeros(201, bool); f[50] = f[120] = True
    r = rmssd(NNSeries.from_times(t, flagged=f))
    assert math.isclose(r.coverage, 196 / 200) and math.isclose(r.valid_s, 196 * 0.9)
    assert math.isclose(r.span_s, 180.0) and "coverage 98%" in str(r)
