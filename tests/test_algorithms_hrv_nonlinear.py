"""Poincare SD1/SD2, DFA alpha1, sample entropy: values, holes, minimum windows."""
import math
import numpy as np
import pytest
from algorithms import NNSeries, poincare, dfa_alpha1, sample_entropy, rmssd, sdnn
from algorithms.hrv_nonlinear import dfa_alpha1_raw, sample_entropy_raw


def white(n, seed=5, mean=800.0, sd=40.0):
    return mean + sd * np.random.default_rng(seed).standard_normal(n)


# ------------------------------------------------------------------ Poincare
def test_sd1_sd2_definitions():
    x = white(400)
    r = poincare(NNSeries.from_intervals(x))
    a, b = x[:-1], x[1:]
    assert math.isclose(r["sd1"].value, np.std(b - a, ddof=1) / math.sqrt(2))
    assert math.isclose(r["sd2"].value, np.std(a + b, ddof=1) / math.sqrt(2))
    # the ellipse identity: SD1^2 + SD2^2 = var(NN[n]) + var(NN[n+1])
    assert math.isclose(r["sd1"].value ** 2 + r["sd2"].value ** 2, np.var(a, ddof=1) + np.var(b, ddof=1))


def test_sd1_is_rmssd_over_root_two_when_the_mean_difference_is_zero():
    nn = NNSeries.from_intervals([800.0, 860.0] * 100 + [800.0])
    assert math.isclose(poincare(nn)["sd1"].value, rmssd(nn).value / math.sqrt(2), rel_tol=1e-2)


def test_poincare_pairs_do_not_cross_a_hole():
    t = np.concatenate([np.arange(0, 150) * 0.8, 120.0 + np.arange(0, 150) * 1.0])
    f = np.zeros(300, bool); f[150] = True
    r = poincare(NNSeries.from_times(t, flagged=f, clean=False))
    assert math.isclose(r["sd1"].value, 0.0, abs_tol=1e-9)        # no (800, 1000) pair exists
    assert r["sd2"].value > 100.0


def test_poincare_minimum_windows():
    short = poincare(NNSeries.from_intervals(white(70)))           # ~56 s
    assert short["sd1"].value is None and short["sd2"].value is None
    mid = poincare(NNSeries.from_intervals(white(100)))            # ~80 s
    assert mid["sd1"].ok and mid["sd2"].value is None and "120 s" in mid["sd2"].withheld
    assert all(r.ok for r in poincare(NNSeries.from_intervals(white(160))).values())


# ----------------------------------------------------------------------- DFA
def test_dfa_alpha1_of_known_processes():
    assert 0.45 < dfa_alpha1(NNSeries.from_intervals(white(2000))).value < 0.70
    walk = 800.0 + np.cumsum(np.random.default_rng(6).standard_normal(2000))
    assert 1.35 < dfa_alpha1(NNSeries.from_intervals(walk)).value < 1.65


def test_dfa_matches_neurokit_on_a_gap_free_series():
    nk = pytest.importorskip("neurokit2")
    x = white(500, seed=7)
    ref, _ = nk.fractal_dfa(x, scale=np.arange(4, 17), overlap=False, integrate=True, order=1)
    assert abs(dfa_alpha1(NNSeries.from_intervals(x)).value - ref) < 1e-9


def test_dfa_boxes_do_not_cross_a_hole():
    x = white(600, seed=8)
    t = np.concatenate([[0.0], np.cumsum(x) / 1000.0])
    f = np.zeros(601, bool); f[300] = True                         # splits into runs of 299 and 299
    nn = NNSeries.from_times(t, flagged=f, clean=False)
    r = dfa_alpha1(nn)
    assert r.n_used == 598
    assert math.isclose(r.value, dfa_alpha1_raw([x[:299], x[301:]]))
    # a level step across the hole would bend F(n) if a box spanned it; it must not
    y = x.copy(); y[301:] += 150.0
    t2 = np.concatenate([[0.0], np.cumsum(y) / 1000.0])
    stepped = dfa_alpha1(NNSeries.from_times(t2, flagged=f, clean=False))
    assert abs(stepped.value - r.value) < 0.05


def test_dfa_ignores_runs_shorter_than_the_largest_box():
    x = white(400, seed=9)
    t = np.concatenate([[0.0], np.cumsum(x) / 1000.0])
    f = np.zeros(401, bool); f[200] = f[210] = True                # a 9-interval run in the middle
    r = dfa_alpha1(NNSeries.from_times(t, flagged=f, clean=False))
    assert r.n_used == 199 + 189


def test_dfa_minimum_window():
    r = dfa_alpha1(NNSeries.from_intervals(white(190)))            # 152 s but only 190 intervals
    assert r.value is None and "needs 200" in r.withheld
    r = dfa_alpha1(NNSeries.from_intervals(white(250, mean=450.0, sd=20.0)))   # 250 intervals, 112 s
    assert r.value is None and "120 s" in r.withheld
    x = white(400, seed=10)
    t = np.concatenate([[0.0], np.cumsum(x) / 1000.0])
    f = np.zeros(401, bool); f[::12] = True                        # only short runs survive
    r = dfa_alpha1(NNSeries.from_times(t, flagged=f, clean=False))
    assert r.value is None and "runs of 16" in r.withheld


# ------------------------------------------------------------ sample entropy
def brute_sampen(runs, r, m=2):
    def count(length):
        tpl = [run[i:i + length] for run in runs for i in range(len(run) - m)]
        return sum(1 for i in range(len(tpl)) for j in range(i + 1, len(tpl))
                   if max(abs(a - b) for a, b in zip(tpl[i], tpl[j])) <= r)
    return -math.log(count(m + 1) / count(m))


def test_sampen_of_white_noise_is_the_theoretical_value():
    v = sample_entropy(NNSeries.from_intervals(white(1500, seed=11))).value
    assert abs(v - (-math.log(math.erf(0.1)))) < 0.15              # 2.185


def test_sampen_of_a_regular_series_is_near_zero():
    x = 800.0 + 40.0 * np.sin(2 * np.pi * np.arange(400) / 10.0)
    assert sample_entropy(NNSeries.from_intervals(x)).value < 0.1


def test_sampen_matches_a_brute_force_count_and_neurokit():
    x = white(300, seed=12)
    r = sample_entropy(NNSeries.from_intervals(x))
    assert math.isclose(r.value, brute_sampen([list(x)], 0.2 * np.std(x, ddof=1)), rel_tol=1e-12)
    nk = pytest.importorskip("neurokit2")
    ref, _ = nk.entropy_sample(x, delay=1, dimension=2, tolerance=0.2 * np.std(x, ddof=1))
    assert abs(r.value - ref) < 1e-9


def test_sampen_templates_do_not_cross_a_hole():
    x = white(300, seed=13)
    t = np.concatenate([[0.0], np.cumsum(x) / 1000.0])
    f = np.zeros(301, bool); f[100] = f[180] = True
    nn = NNSeries.from_times(t, flagged=f, clean=False)
    r = sample_entropy(nn)
    runs = [list(x[:99]), list(x[101:179]), list(x[181:])]
    assert r.n_used == sum(len(q) - 2 for q in runs)
    assert math.isclose(r.value, brute_sampen(runs, 0.2 * np.std(nn.values, ddof=1)), rel_tol=1e-12)


def test_sampen_minimum_window():
    r = sample_entropy(NNSeries.from_intervals(white(210)))        # 168 s
    assert r.value is None and "180 s" in r.withheld
    r = sample_entropy(NNSeries.from_intervals(white(190, mean=1000.0)))   # 190 s, 188 templates
    assert r.value is None and "needs 200" in r.withheld
    assert sample_entropy(NNSeries.from_intervals(white(260))).ok


def test_sampen_undefined_is_withheld_not_infinite():
    v, n = sample_entropy_raw([np.array([1.0, 50.0, 3.0, 400.0, 9.0, 1000.0])], 0.001)
    assert v != v and n == 4
    spread = 800.0 + 200.0 * np.sin(np.arange(260) ** 2.0)         # no two triples alike
    r = sample_entropy(NNSeries.from_intervals(spread))
    assert r.value is None or math.isfinite(r.value)
