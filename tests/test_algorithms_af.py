"""AF screening features, gate and the frozen model file (algorithms/af.py)."""
import math
import numpy as np
import algorithms as A
from algorithms import af

MEDIAN_REST = dict(v_share=0.0, s_share=0.0, ect_und=0.42, flag_share=0.19)   # cold-start medians, analysis/af_cinc_cv.txt


def _feats(rr):
    return {**af.rr_features(rr), **MEDIAN_REST}


def test_regular_and_irregular_rhythms_separate():
    rng = np.random.default_rng(0)
    regular = 0.8 + 0.005 * rng.standard_normal(35)
    irregular = rng.uniform(0.4, 1.1, 35)
    a, b = af.rr_features(regular), af.rr_features(irregular)
    assert a["n_rr"] == b["n_rr"] == 35
    assert a["ln_nrmssd"] < -3.5 < -1.5 < b["ln_nrmssd"]
    assert a["cosen"] < b["cosen"]
    assert abs(b["tpr"] - 2 / 3) < 0.15            # a random series turns at 2/3 of its points
    assert abs(b["ln_sd1_sd2"]) < 0.5              # successive intervals unrelated: SD1 about SD2


def test_slow_drift_has_few_turning_points():
    rr = 0.8 + 0.1 * np.sin(np.arange(40) / 6.0)
    f = af.rr_features(rr)
    assert f["tpr"] < 0.2 and f["ln_sd1_sd2"] < -1.5


def test_nothing_is_differenced_across_a_break():
    rr = np.array([0.8] * 10 + [np.nan] + [1.2] * 10)
    f = af.rr_features(rr)
    assert f["n_rr"] == 20
    assert f["ln_nrmssd"] == math.log(1e-6)        # no successive difference inside either run
    assert f["tpr"] == 0.0


def test_cosen_matches_its_definition():
    rr = np.array([0.80, 0.81, 0.80, 0.82, 0.80, 0.81, 0.79, 0.80, 0.81, 0.80])
    cfg = dict(cosen_r_s=0.03, cosen_r_step_s=0.01, cosen_r_max_s=0.3, cosen_min_a=5)
    t = np.lib.stride_tricks.sliding_window_view(rr, 2)
    a = b = 0
    for i in range(len(t)):
        for j in range(i + 1, len(t)):
            if abs(t[i, 0] - t[j, 0]) <= 0.03:
                b += 1
                a += abs(t[i, 1] - t[j, 1]) <= 0.03
    want = -math.log(a / b) + math.log(0.06) - math.log(rr.mean())
    assert abs(af.cosen([rr], float(rr.mean()), cfg) - want) < 1e-12


def test_gate_withholds_short_windows():
    f = _feats(0.8 + 0.01 * np.arange(6))
    assert "needs" in af.judged(f)
    model = af.load_model()
    assert af.label_of(model, f)[0] == "~"
    assert af.judged(_feats(0.8 + 0.01 * np.sin(np.arange(30)))) is None


def test_model_file_is_frozen_and_gives_probabilities():
    model = af.load_model()
    assert A.CONFIG["af"]["frozen"] == model["frozen"]
    assert model["classes"] == af.CLASSES and model["features"] == af.FEATURES
    rng = np.random.default_rng(1)
    for rr in (0.8 + 0.005 * rng.standard_normal(35), rng.uniform(0.4, 1.1, 35)):
        p = af.probabilities(model, _feats(rr))
        assert len(p) == 4 and abs(p.sum() - 1.0) < 1e-12 and np.all(p >= 0)


def test_model_separates_a_steady_from_a_random_rhythm():
    model = af.load_model()
    rng = np.random.default_rng(2)
    steady = af.label_of(model, _feats(0.8 + 0.005 * rng.standard_normal(35)))[0]
    random_ = af.label_of(model, {**_feats(rng.uniform(0.4, 1.1, 45)), "s_share": 0.11})[0]
    # The steady series is white 5 ms jitter, which no real rhythm is (it turns at 2/3 of
    # its points); the model calls it 'O'. What the screen must get right is A or not A.
    assert steady in ("N", "O") and random_ == "A"
