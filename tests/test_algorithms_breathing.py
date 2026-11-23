"""ECG-derived breathing rate: both modulations, the fusion, and what is withheld."""
import math
import numpy as np
from algorithms import Modulations, modulations, r_amplitudes, breathing_rate, rate_from_spectra, CONFIG
from algorithms import frontend

FS = 256.0


def synth_beats(duration_s, br_hz, mean_s=0.8, rsa_s=0.04):
    t = [0.5]
    while t[-1] < duration_s - 1.0:
        t.append(t[-1] + mean_s + rsa_s * math.sin(2 * math.pi * br_hz * t[-1]))
    return np.array(t)


def mods_from(t, br_hz, rsa=True, amp=True, seed=0):
    rng = np.random.default_rng(seed)
    nn = 1000.0 * np.diff(t)
    rsa_v = nn if rsa else 800.0 + 30.0 * rng.standard_normal(len(nn))
    amp_v = 1.0 + 0.1 * np.sin(2 * np.pi * br_hz * t) if amp else 1.0 + 0.1 * rng.standard_normal(len(t))
    return Modulations(t, t[1:], rsa_v, t, amp_v)


def synth_ecg(t_beats, br_hz, duration_s, amp_mod=0.15, seed=1):
    """Gaussian R waves (sigma 10 ms) whose height follows breathing, small T
    waves, a little noise."""
    n = int(duration_s * FS)
    ts = np.arange(n) / FS
    x = 0.01 * np.random.default_rng(seed).standard_normal(n)
    for tb in t_beats:
        a = 1.0 + amp_mod * math.sin(2 * math.pi * br_hz * tb)
        k0, k1 = max(0, int((tb - 0.5) * FS)), min(n, int((tb + 0.5) * FS))
        seg = ts[k0:k1]
        x[k0:k1] += a * np.exp(-0.5 * ((seg - tb) / 0.010) ** 2) + 0.2 * np.exp(-0.5 * ((seg - tb - 0.25) / 0.04) ** 2)
    return x


def test_each_modulation_and_the_fusion_find_the_rate():
    for bpm in (8.0, 15.0, 24.0):
        m = mods_from(synth_beats(40.0, bpm / 60.0), bpm / 60.0)
        r = breathing_rate(m, 2.0, 34.0)
        for key in ("rsa", "ramp", "fused"):
            assert r[key].ok and abs(r[key].value - bpm) < 0.7, (bpm, key, r[key])
            assert r[key].unit == "breaths/min" and 0.3 <= r[key].extra["share"] <= 1.0


def spectra_with(rsa_peaks, ramp_peaks, W=32.0, n_beats=40):
    """A window_spectra() result with chosen peaks: lists of (breaths/min, share of power)."""
    f = np.linspace(4.0 / 60, 40.0 / 60, 155)

    def spec(peaks):
        if peaks is None:
            return (None, "too few usable beats", 3)
        p = np.full(len(f), (1.0 - sum(s for _, s in peaks)) / len(f))
        for bpm, share in peaks:
            p[int(np.argmin(np.abs(f - bpm / 60.0)))] += share
        return (p / p.sum(), None, n_beats)
    return dict(W=W, n_beats=n_beats, f=f, why=None, rsa=spec(rsa_peaks), ramp=spec(ramp_peaks))


def test_shipped_fusion_reports_agreement_or_a_strong_r_amplitude_peak():
    assert CONFIG["breathing"]["fusion"] == "agree_or_ramp"
    both = rate_from_spectra(spectra_with([(15.0, 0.5)], [(16.0, 0.35)]))
    assert abs(both["fused"].value - 15.5) < 0.3 and both["fused"].extra["n_spectra"] == 2
    strong_ramp = rate_from_spectra(spectra_with([(6.0, 0.7)], [(18.0, 0.5)]))      # they disagree
    assert abs(strong_ramp["fused"].value - 18.0) < 0.3 and strong_ramp["fused"].extra["n_spectra"] == 1
    assert abs(strong_ramp["rsa"].value - 6.0) < 0.3                                # still shown on its own
    weak_ramp = rate_from_spectra(spectra_with([(6.0, 0.7)], [(18.0, 0.28)]))      # peak share 0.36: between the two limits
    assert 0.3 <= weak_ramp["ramp"].extra["share"] < 0.4
    assert weak_ramp["fused"].value is None and "disagree" in weak_ramp["fused"].withheld
    rsa_alone = rate_from_spectra(spectra_with([(15.0, 0.8)], [(18.0, 0.1)]))       # RSA is never reported alone
    assert rsa_alone["rsa"].ok and rsa_alone["ramp"].value is None and rsa_alone["fused"].value is None
    no_ramp = rate_from_spectra(spectra_with([(15.0, 0.8)], None))
    assert no_ramp["fused"].value is None
    ramp_only = rate_from_spectra(spectra_with(None, [(18.0, 0.6)]))
    assert abs(ramp_only["fused"].value - 18.0) < 0.3
    neither = rate_from_spectra(spectra_with(None, None))
    assert "enough usable beats" in neither["fused"].withheld


def test_the_other_fusion_rules():
    sp = spectra_with([(6.0, 0.6)], [(18.0, 0.45)])
    assert abs(rate_from_spectra(sp, {"fusion": "best_share"})["fused"].value - 6.0) < 0.3
    assert rate_from_spectra(sp, {"fusion": "agree"})["fused"].value is None
    avg = rate_from_spectra(sp, {"fusion": "average"})["fused"]
    assert abs(avg.value - 6.0) < 0.3 and avg.extra["n_spectra"] == 2
    sp = spectra_with([(6.0, 0.5), (18.0, 0.3)], [(18.0, 0.45)])                    # only 18 is in both
    assert abs(rate_from_spectra(sp, {"fusion": "product"})["fused"].value - 18.0) < 0.3
    assert abs(rate_from_spectra(sp, {"fusion": "best_share"})["fused"].value - 6.0) < 0.3
    close = spectra_with([(15.0, 0.5)], [(17.0, 0.5)])
    assert abs(rate_from_spectra(close, {"fusion": "agree"})["fused"].value - 16.0) < 0.3
    assert rate_from_spectra(close, {"fusion": "agree", "agree_bpm": 1.0})["fused"].value is None
    one = spectra_with([(15.0, 0.5)], None)
    assert abs(rate_from_spectra(one, {"fusion": "product"})["fused"].value - 15.0) < 0.3
    assert rate_from_spectra(one, {"fusion": "agree"})["fused"].value is None


def test_peak_share_gate_and_band_edges():
    low = rate_from_spectra(spectra_with([(15.0, 0.2)], [(15.0, 0.2)]))
    assert all(v.value is None for v in low.values()) and "needs 30%" in low["ramp"].withheld
    edge = rate_from_spectra(spectra_with([(4.0, 0.8)], [(40.0, 0.8)]))
    assert "no peak inside" in edge["rsa"].withheld and "no peak inside" in edge["ramp"].withheld
    assert edge["fused"].value is None


def test_fused_from_real_series():
    t = synth_beats(40.0, 0.25)
    only_rsa = breathing_rate(mods_from(t, 0.25, amp=False), 2.0, 34.0)
    assert abs(only_rsa["rsa"].value - 15.0) < 0.7
    assert only_rsa["fused"].value is None or abs(only_rsa["fused"].value - 15.0) < 3.0
    only_amp = breathing_rate(mods_from(t, 0.25, rsa=False), 2.0, 34.0)
    assert only_amp["ramp"].ok and abs(only_amp["fused"].value - 15.0) < 0.7


def test_noise_alone_is_withheld():
    t = np.cumsum(np.full(60, 0.8))
    held = 0
    for seed in range(20):
        r = breathing_rate(mods_from(t, 0.25, rsa=False, amp=False, seed=seed), 0.0, 32.0)
        held += r["fused"].value is None
    assert held >= 18                                    # the gates reject nearly every noise window


def test_window_shorter_than_the_minimum_is_withheld():
    m = mods_from(synth_beats(40.0, 0.25), 0.25)
    r = breathing_rate(m, 2.0, 22.0)
    assert all(v.value is None and "needs 32 s" in v.withheld for v in r.values())
    assert CONFIG["breathing"]["window_s"] == 32.0


def test_too_few_usable_beats_is_withheld():
    t = synth_beats(40.0, 0.25)
    m = mods_from(t, 0.25)
    sparse = Modulations(t, m.rsa_t[::4], m.rsa_v[::4], m.amp_t[::4], m.amp_v[::4])
    r = breathing_rate(sparse, 2.0, 34.0)
    assert all(v.value is None for v in r.values())
    assert "usable" in r["rsa"].withheld and "usable" in r["ramp"].withheld
    empty = breathing_rate(Modulations(t[:5], t[1:5], m.rsa_v[:4], t[:5], m.amp_v[:5]), 0.0, 32.0)
    assert "beats in the window" in empty["fused"].withheld


def test_nothing_is_reported_above_half_the_heart_rate():
    t = synth_beats(40.0, 0.5, mean_s=1.2, rsa_s=0.03)   # 50 beats/min, breathing 30/min
    r = breathing_rate(mods_from(t, 0.5), 2.0, 34.0)
    for v in r.values():
        assert v.value is None or v.value <= 25.5         # 30/min is beyond what 50 beats/min can show


def test_constant_series_is_withheld():
    t = np.cumsum(np.full(60, 0.8))
    m = Modulations(t, t[1:], np.full(59, 800.0), t, np.full(60, 1.0))
    r = breathing_rate(m, 0.0, 40.0)
    assert all(v.value is None for v in r.values())


def test_an_ectopic_amplitude_does_not_decide_the_rate():
    t = synth_beats(40.0, 0.25)
    m = mods_from(t, 0.25)
    amp = m.amp_v.copy(); amp[[10, 25]] = 5.0             # two beats five times the size
    r = breathing_rate(Modulations(t, m.rsa_t, m.rsa_v, t, amp), 2.0, 34.0)
    assert abs(r["ramp"].value - 15.0) < 0.7


def test_r_amplitudes_follow_the_r_wave():
    t = synth_beats(40.0, 0.2)
    x = synth_ecg(t, 0.2, 40.0)
    beats = frontend.detect(x, FS)
    assert abs(len(beats) - len(t)) <= 2
    for mode in ("baseline", "peak_to_peak"):
        a = r_amplitudes(x, beats, FS, mode, flagged=False)
        ok = np.isfinite(a)
        bt = np.array([b["pos"] for b in beats]) / FS
        truth = 1.0 + 0.15 * np.sin(2 * np.pi * 0.2 * bt[ok])
        assert ok.sum() >= len(beats) - 12                # the first beats are flagged (no polarity yet)
        assert np.corrcoef(a[ok], truth)[0, 1] > 0.95, mode
        assert np.all(np.abs(a[ok] / truth - 1.0) < 0.12), mode
    assert beats[0]["flagged"]
    assert np.isnan(r_amplitudes(x, beats, FS, "peak_to_peak", flagged=False)[0])   # flagged beat -> no amplitude
    assert np.isnan(r_amplitudes(x, beats, FS, "baseline", flagged=True)[0])        # baseline needs the tp2 position
    with_flagged = r_amplitudes(x, beats, FS, "peak_to_peak", flagged=True)         # max - min does not
    assert np.isfinite(with_flagged[1:-1]).all()
    late = [i for i, b in enumerate(beats) if b["flagged"] and b["pos"] > 2.0 * FS]  # after the detector's warm-up
    assert late and all(abs(with_flagged[i] - 1.0) < 0.25 for i in late)


def test_end_to_end_from_ecg_samples():
    for causal in (False, True):
        t = synth_beats(60.0, 12.0 / 60.0)
        x = synth_ecg(t, 12.0 / 60.0, 60.0)
        y = frontend.filter_ecg(x, FS, 50.0, causal=causal)
        beats = frontend.detect(y, FS)
        m = modulations(y, beats, FS)
        r = breathing_rate(m, 20.0, 52.0)
        for key in ("rsa", "ramp", "fused"):
            assert r[key].ok and abs(r[key].value - 12.0) < 1.0, (causal, key, str(r[key]))
        assert r["fused"].coverage > 0.9
