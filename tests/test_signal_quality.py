"""The app's quality gate, Python reference (signal_quality.py): the artifact check."""
import numpy as np
import signal_quality as SQ

FS = 256.0


def beats(seconds, rr_s=0.8, amp=100.0, seed=0):
    """A display-like signal: a narrow spike of `amp` every rr_s on small noise."""
    rng = np.random.default_rng(seed)
    x = 2.0 * rng.standard_normal(int(seconds * FS))
    for t in np.arange(0.4, seconds - 0.1, rr_s):
        i = int(t * FS); x[i - 3:i + 4] += amp * np.hanning(7)
    return x.astype(np.float32)


def run(x):
    """artifact state after every completed 1 s block."""
    g = SQ.SignalQuality(FS); out = []
    for i, v in enumerate(x):
        g.track(v)
        if (i + 1) % 256 == 0:
            out.append(g.artifact_state()[0])
    return out, g


def test_clean_beats_are_never_an_artifact():
    assert not any(run(beats(60))[0])


def test_slow_heart_rate_is_not_an_artifact():
    # 45 beats/min: a quarter of the seconds hold no beat. The median second still does.
    assert not any(run(beats(90, rr_s=60 / 45))[0])


def test_transient_is_poor_for_ten_blocks_then_recovers():
    x = beats(60)
    x[int(30.5 * FS)] += 3000.0                     # 30 times a beat, in block 30 (0-based)
    art, _ = run(x)
    assert not any(art[:30])
    assert all(art[30:40])                          # that block and the 9 after it
    assert not any(art[40:])


def test_block_being_filled_counts_at_once():
    x = beats(40)
    g = SQ.SignalQuality(FS)
    for v in x[:int(30 * FS)]:
        g.track(v)
    assert not g.artifact_state()[0]
    g.track(1.0); g.track(3000.0)                   # two samples into block 30
    art, ratio = g.artifact_state()
    assert art and ratio > 20


def test_verdict_is_poor_during_an_artifact_and_says_why():
    x = beats(40); x[int(30.5 * FS)] += 3000.0
    q = SQ.qrs_signal(x, FS)
    g = SQ.SignalQuality(FS)
    for v in x[:int(32 * FS)]:
        g.track(v)
    n = int(32 * FS)
    r = g.assess(x[n - 1280:n], q[n - 1280:n])
    assert r["artifact"] and r["level"] == "POOR" and r["label"] == SQ.LABELS["ARTIFACT"]
    assert r["level_kp"] == SQ.level_of(r["k"], r["p"])


def test_reference_is_the_lower_median_of_the_last_30_swings():
    g = SQ.SignalQuality(FS)
    for s in [10.0, 20.0, 30.0, 40.0]:
        for v in [0.0] * 255 + [s]:
            g.track(v)
    assert g.reference == 20.0
    assert g.memory == 30 and g.hold_blocks == 10 and g.ratio_max == 4.0
