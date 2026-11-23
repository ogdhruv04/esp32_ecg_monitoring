"""NNSeries, the result type and the minimum-window gate."""
import math
import numpy as np
import pan_tompkins as PT
from algorithms import NNSeries, gate, minimum, CONFIG


def beats_from(times_s, fs=256.0, flagged=(), searchback=(), gap=()):
    return [dict(pos=t * fs, bp=int(t * fs), kind="searchback" if i in searchback else "primary",
                 flagged=i in flagged, gap=i in gap) for i, t in enumerate(times_s)]


def test_from_intervals_is_gap_free():
    nn = NNSeries.from_intervals([800.0] * 100)
    assert nn.n_intervals == 100 and nn.n_accepted == 100 and nn.coverage == 1.0
    assert math.isclose(nn.valid_s, 80.0) and math.isclose(nn.span_s, 80.0)
    assert len(nn.beat_t) == 101 and len(nn.runs()) == 1


def test_flagged_beat_removes_both_its_intervals():
    t = np.arange(0, 41) * 0.8
    f = np.zeros(41, bool); f[20] = True
    nn = NNSeries.from_times(t, flagged=f)
    assert nn.n_intervals == 40 and nn.n_accepted == 38
    assert not nn.accepted[19] and not nn.accepted[20]
    a, b = nn.pairs()
    assert len(a) == 36                      # 39 neighbouring entries, 3 touch the hole
    assert [len(r) for r in nn.runs()] == [19, 19]
    assert math.isclose(nn.coverage, 38 / 40)
    assert math.isclose(nn.span_s, 32.0) and math.isclose(nn.valid_s, 38 * 0.8)


def test_from_beats_is_the_detectors_own_series():
    rng = np.random.default_rng(1)
    t = np.cumsum(0.8 + 0.03 * rng.standard_normal(200))
    beats = beats_from(t, flagged={30, 31, 90}, searchback={50}, gap={120})
    nn = NNSeries.from_beats(beats, 256.0)
    rr = PT.rr_history(beats, 256.0, depth=10**6)
    acc, _ = PT.clean_nn(rr)
    assert nn.n_intervals == len(rr) == 199
    assert np.array_equal(nn.accepted, np.array(acc))
    assert np.allclose(nn.values, np.array(rr)[np.array(acc)])
    for i in (29, 30, 31, 49, 50, 89, 90, 119):      # the interval ending at beat i+1
        assert not nn.accepted[i]
    assert nn.accepted[120]


def test_cleaning_drops_out_of_range_and_jumps():
    rr = [800.0] * 20 + [1600.0] + [800.0] * 20 + [250.0] + [800.0] * 10
    nn = NNSeries.from_intervals(rr, clean=True)
    assert not nn.accepted[20] and not nn.accepted[41] and nn.n_accepted == len(rr) - 2


def test_window_keeps_intervals_with_both_beats_inside():
    nn = NNSeries.from_intervals([1000.0] * 60)          # beats at 0, 1, ... 60 s
    w = nn.window(10.0, 20.0)                            # beats 10 .. 19
    assert len(w.beat_t) == 10 and w.n_intervals == 9
    assert w.beat_t[0] == 10.0 and w.beat_t[-1] == 19.0
    assert nn.window(100.0, 200.0).n_intervals == 0
    assert nn.window(10.0, 10.5).n_intervals == 0


def test_gate_counts_valid_time_not_clock_time():
    t = np.arange(0, 301) * 1.0                          # 300 s of beats
    f = np.zeros(301, bool); f[::3] = True               # every third beat flagged
    nn = NNSeries.from_times(t, flagged=f)
    assert nn.span_s == 300.0 and math.isclose(nn.valid_s, 100.0)
    assert gate(nn, "rmssd") is None                     # needs 60 s
    assert "needs 120 s" in gate(nn, "sdnn")             # 100 s valid in a 300 s window


def test_every_measure_has_a_documented_minimum():
    for name in ("rmssd", "sdnn", "pnn50", "hf", "lf", "sd1", "sd2", "dfa_alpha1", "sampen"):
        assert minimum(name)["valid_s"] >= 60
    assert minimum("rmssd")["nn"] == PT.MIN_BEATS_FOR_HRV   # never laxer than the frozen tp2.1 rule
    assert CONFIG["hrv"]["dfa"] == {"scale_min": 4, "scale_max": 16}


def test_session_rules_are_in_the_config():
    s = CONFIG["session"]                                 # read by the app's session_reference.py
    assert s["hr_min_intervals"] == 60 and s["breathing_min_windows"] == 5
    assert s["breathing_max_range_bpm"] == 6.0 and s["frozen"]
