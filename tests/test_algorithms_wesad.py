"""WESAD loader: the restricted unpickler, segments, the reference half, windows.
No test needs the dataset: each builds a small file in WESAD's own layout."""
import os, pickle, zipfile
import numpy as np
import pytest
from algorithms import wesad


def fake_dict(minutes=None, subject="S99"):
    """A recording in the layout of SX.pkl. minutes: [(label, minutes), ...]."""
    minutes = minutes or [(0, 1), (1, 20), (0, 2), (2, 10), (0, 3), (4, 7), (0, 1), (3, 6.5), (0, 1), (4, 7), (0, 1)]
    label = np.concatenate([np.full(int(m * 60 * 700), c, dtype=np.int32) for c, m in minutes])
    n = len(label); dur = n / 700.0
    rng = np.random.default_rng(0)
    col = lambda k: rng.standard_normal((k, 1))
    return {"subject": subject, "label": label,
            "signal": {"chest": {"ECG": col(n), "EDA": col(n) + 5, "Temp": col(n) + 33, "ACC": rng.standard_normal((n, 3)),
                                 "EMG": col(n), "Resp": col(n)},
                       "wrist": {"BVP": col(int(dur * 64)), "EDA": col(int(dur * 4)) + 1, "TEMP": col(int(dur * 4)) + 32,
                                 "ACC": rng.standard_normal((int(dur * 32), 3))}}}


def test_reads_a_pickle_of_arrays(tmp_path):
    p = tmp_path / "S99.pkl"
    with open(p, "wb") as f:
        pickle.dump(fake_dict(), f, protocol=2)
    rec = wesad.from_dict(wesad.read_pkl(p))
    assert rec.subject == "S99" and rec.ecg.ndim == 1 and rec.ecg.dtype == np.float32
    assert len(rec.label) == len(rec.ecg) and rec.label.dtype == np.uint8
    d = rec.durations()
    assert max(d.values()) - min(d.values()) < 0.5


class _Evil:
    def __reduce__(self):
        return (os.system, ("echo should-never-run",))


def test_refuses_a_pickle_that_would_run_code(tmp_path):
    p = tmp_path / "evil.pkl"
    with open(p, "wb") as f:
        pickle.dump({"subject": "S99", "x": _Evil()}, f, protocol=2)
    with pytest.raises(pickle.UnpicklingError, match="refusing"):
        wesad.read_pkl(p)


def test_extract_and_load_round_trip(tmp_path):
    z = tmp_path / "WESAD.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("WESAD/S99/S99.pkl", pickle.dumps(fake_dict(), protocol=2))
    a = wesad.extract(z, tmp_path / "cache", "S99")
    b = wesad.load(tmp_path / "cache", "S99")
    assert np.array_equal(a.ecg, b.ecg) and np.array_equal(a.label, b.label) and np.array_equal(a.bvp, b.bvp)
    assert not [f for f in os.listdir(tmp_path / "cache") if "tmp" in f]


def test_wrong_subject_inside_the_file_is_an_error(tmp_path):
    z = tmp_path / "WESAD.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("WESAD/S98/S98.pkl", pickle.dumps(fake_dict(subject="S99"), protocol=2))
    with pytest.raises(ValueError, match="says it is"):
        wesad.extract(z, tmp_path / "cache", "S98")


def test_segments_take_the_longest_run_and_both_meditations():
    lab = np.concatenate([np.full(700 * s, c, dtype=np.uint8) for c, s in
                          [(0, 10), (1, 5), (0, 2), (1, 600), (2, 300), (4, 100), (3, 200), (4, 120), (7, 50)]])
    segs = wesad.segments(wesad.label_runs(lab, 700.0))
    assert segs["baseline"] == (17.0, 617.0)            # the 600 s run, not the 5 s one
    assert segs["stress"] == (617.0, 917.0) and segs["amusement"] == (1017.0, 1217.0)
    assert segs["meditation_1"] == (917.0, 1017.0) and segs["meditation_2"] == (1217.0, 1337.0)


def test_missing_condition_is_an_error():
    lab = np.concatenate([np.full(700 * 60, c, dtype=np.uint8) for c in (1, 2)])
    with pytest.raises(ValueError, match="amusement"):
        wesad.segments(wesad.label_runs(lab, 700.0))


def test_baseline_is_cut_into_reference_and_class_halves():
    p = wesad.parts({"baseline": (100.0, 1300.0), "stress": (2000.0, 2600.0), "amusement": (3000.0, 3392.0)})
    assert p["reference"] == (100.0, 700.0) and p["baseline"] == (700.0, 1300.0)
    assert p["stress"] == (2000.0, 2600.0)


def test_windows_stay_inside_their_part_and_never_straddle_the_cut():
    p = wesad.parts({"baseline": (100.0, 1300.0), "stress": (2000.0, 2600.0), "amusement": (3000.0, 3392.0)})
    w = wesad.windows(p)
    for name, t0, t1 in w:
        assert t1 - t0 == 180.0 and p[name][0] <= t0 and t1 <= p[name][1]
    count = lambda n: sum(1 for x in w if x[0] == n)
    assert count("reference") == 15 and count("baseline") == 15      # (600 - 180) / 30 + 1
    assert count("stress") == 15 and count("amusement") == 8         # (392 - 180) / 30 + 1
    assert [x[1] for x in w if x[0] == "stress"][:2] == [2000.0, 2030.0]


def test_a_part_shorter_than_a_window_gives_none():
    assert wesad.windows({"stress": (0.0, 179.0)}) == []


def test_order_from_the_labels():
    rec = wesad.from_dict(fake_dict())
    assert rec.order() == "stress_first"
    assert set(rec.parts()) == {"reference", "baseline", "stress", "amusement", "meditation_1", "meditation_2"}
