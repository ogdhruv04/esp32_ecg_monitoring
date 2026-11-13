"""Ectopic-beat labels: shape against the normal template, timing against the normal rhythm."""
import math
import numpy as np
from algorithms import ectopic, frontend, CONFIG

FS = 256.0


def record(duration_s=120.0, pvc_every=None, apc_every=None, change_at=None, seed=0, pvc_from=0.0):
    """Synthetic ECG. Normal beat: one narrow positive lobe. PVC: early, wide and
    inverted, followed by a pause. APC: early, normal shape. After change_at every
    beat has a new (biphasic) shape. Returns (signal, beat times, kinds)."""
    rng = np.random.default_rng(seed)
    n = int(duration_s * FS); ts = np.arange(n) / FS
    x = 0.01 * rng.standard_normal(n)
    t, kinds, k = 1.0, [], 0
    times = []
    while t < duration_s - 2.0:
        kind = "N"
        if pvc_every and t >= pvc_from and k % pvc_every == pvc_every - 1:
            kind = "V"
        elif apc_every and k % apc_every == apc_every - 1:
            kind = "S"
        rr = 0.85 + 0.01 * rng.standard_normal()
        if kind in "VS":
            t -= 0.30                                   # 35% early
        k0, k1 = max(0, int((t - 0.4) * FS)), min(n, int((t + 0.4) * FS)); s = ts[k0:k1] - t
        if kind == "V":
            x[k0:k1] += -1.2 * np.exp(-0.5 * (s / 0.030) ** 2) + 0.5 * np.exp(-0.5 * ((s - 0.07) / 0.03) ** 2)
        elif change_at is not None and t > change_at:
            x[k0:k1] += 0.8 * np.exp(-0.5 * ((s + 0.012) / 0.010) ** 2) - 0.7 * np.exp(-0.5 * ((s - 0.012) / 0.010) ** 2)
        else:
            x[k0:k1] += np.exp(-0.5 * (s / 0.010) ** 2)
        times.append(t); kinds.append(kind)
        t += rr + (0.30 if kind in "VS" else 0.0)       # compensatory pause
        k += 1
    return x, np.array(times), kinds


def run(x):
    beats = frontend.detect(x, FS)
    return beats, ectopic.classify(x, beats, FS)


def truth_of(beats, times, kinds):
    pos = np.array([b["pos"] for b in beats]) / FS
    return [kinds[int(np.argmin(np.abs(times - p)))] for p in pos]


def test_settings_are_frozen():
    e = CONFIG["ectopic"]
    assert e["frozen"] and (e["r_n"], e["r_v"], e["prem_v"], e["r_vv"]) == (0.97, 0.95, 0.9, 0.7)


def test_label_rule():
    assert ectopic.label(0.5, 0.7) == "V"               # different shape, early
    assert ectopic.label(0.5, 1.0) == "V"               # very different shape decides alone
    assert ectopic.label(0.9, 0.7) == "V" and ectopic.label(0.9, 1.0) == "N"
    assert ectopic.label(0.99, 0.7) == "S" and ectopic.label(0.99, 1.0) == "N"
    assert ectopic.label(math.nan, 0.7) == "U" and ectopic.label(0.99, math.nan) == "U"


def test_normal_rhythm_has_no_ectopic_beats():
    beats, lab = run(record()[0])
    c = ectopic.count(lab)
    assert c["V"] == 0 and c["S"] == 0 and c["U"] <= 22 and c["coverage"] > 0.8
    assert all(q["label"] == "U" for q in lab[:16])     # the detector's first timed beats seed the template


def test_pvcs_are_found_and_normal_beats_left_alone():
    x, times, kinds = record(pvc_every=7)
    beats, lab = run(x)
    truth = truth_of(beats, times, kinds)
    decided = [(q["label"], t) for q, t in zip(lab, truth) if q["label"] != "U"]
    tp = sum(1 for l, t in decided if l == "V" and t == "V"); fn = sum(1 for l, t in decided if l != "V" and t == "V")
    fp = sum(1 for l, t in decided if l == "V" and t != "V")
    assert tp >= 15 and fn <= 1 and fp == 0
    v = [q for q, t in zip(lab, truth) if t == "V" and q["label"] == "V"]
    assert all(q["r"] < 0.8 and q["prem"] < 0.8 for q in v)


def test_bigeminy_is_labelled_right_or_left_undecided():
    x, times, kinds = record(pvc_every=2, pvc_from=30.0)   # normal for 30 s, then every second beat ventricular
    beats, lab = run(x)
    truth = truth_of(beats, times, kinds)
    late = [(q["label"], t) for q, t, b in zip(lab, truth, beats) if b["pos"] > 30 * FS]
    decided = [(l, t) for l, t in late if l != "U"]
    assert sum(1 for l, t in decided if t == "V" and l == "V") >= 10
    assert sum(1 for l, t in decided if t == "V" and l != "V") <= 1
    assert sum(1 for l, t in decided if t == "N" and l == "V") == 0
    # Once the detector can time nothing, the template is rebuilt from mixed
    # beats and the rest is undecided, not mislabelled (module docstring).
    assert sum(1 for l, t in late if l == "U") > 20


def test_bigeminy_from_the_first_beat_is_undecided_not_mislabelled():
    # No stretch of normal rhythm: the detector cannot time any beat (its own
    # median beat is half ventricular), so no template is ever seeded. The
    # honest output is "undecided", and coverage says so.
    x, times, kinds = record(pvc_every=2)
    beats, lab = run(x)
    c = ectopic.count(lab)
    assert c["coverage"] < 0.3 and c["V"] + c["S"] <= 0.3 * len(lab)


def test_premature_beats_of_normal_shape_are_s_not_v():
    x, times, kinds = record(apc_every=9)
    beats, lab = run(x)
    truth = truth_of(beats, times, kinds)
    s = [q["label"] for q, t in zip(lab, truth) if t == "S"]
    assert s.count("S") >= len(s) - 2 and s.count("V") == 0
    assert sum(1 for q, t in zip(lab, truth) if t == "N" and q["label"] == "S") <= 1


def test_a_lasting_change_of_shape_is_learned_as_the_new_normal():
    x, times, kinds = record(duration_s=150.0, change_at=60.0)
    beats, lab = run(x)
    pos = np.array([b["pos"] for b in beats]) / FS
    after = [q["label"] for q, p in zip(lab, pos) if p > 100.0]
    assert after.count("V") == 0 and after.count("N") >= len(after) - 2
    during = [q["label"] for q, p in zip(lab, pos) if 60.5 < p < 100.0]
    assert during.count("V") + during.count("S") <= 3     # a new shape on time is not called ectopic


def test_gap_and_count():
    x, _, _ = record()
    beats = frontend.detect(x, FS)
    y = x.copy(); k = int(beats[40]["bp"]); y[k - 2:k + 2] = np.nan
    lab = ectopic.classify(y, beats, FS)
    assert lab[40]["label"] == "U"
    c = ectopic.count(lab)
    assert c["V"] + c["S"] + c["N"] + c["U"] == len(beats) and 0.8 < c["coverage"] < 1.0
