"""Breathing rate from the ECG alone: two modulations and their fusion.

Breathing changes the ECG in two ways that survive a 0.5 Hz high-pass:

  RSA    respiratory sinus arrhythmia: the NN interval shortens on inspiration.
         Series = accepted NN intervals at their beat times (the same cleaned
         series the HRV measures use).
  RAMP   the R-wave amplitude changes as the heart's axis and the chest
         impedance move. Series = R amplitude at every unflagged tp2.1 beat.

Each is a series sampled once per beat. In a window (32 s by default) it is
cleaned of outliers, detrended, and its Lomb-Scargle spectrum taken over the
breathing band; the rate is the highest peak inside the band. FUSED combines
the two normalised spectra by the rule in config.json ("fusion"):
  average     mean of the spectra that are peaked enough on their own
  product     product of the two spectra, which keeps only what both show;
              one spectrum alone when the other series has too few beats
  agree       both peaks pass on their own and lie within agree_bpm: their mean
  best_share  the one of the two whose peak holds the larger share
  agree_or_ramp  as agree; failing that, the R-amplitude rate alone when its
              peak holds at least ramp_alone_share. RSA is never reported
              alone by this rule: on the BIDMC development subjects a strong
              RSA peak was often a slower rhythm than breathing
              (analysis/breathing_bidmc_dev_tuning.txt).

A rate is WITHHELD, not guessed, when
  - the window is shorter than window_s,
  - fewer than min_beats beats, or less than min_beat_coverage of the window's
    beats, are usable,
  - the spectrum has no peak inside the band (its maximum sits on an edge),
  - the peak holds less than peak_share_min of the band's power.
The band stops at half the beat rate: a rhythm sampled once per beat cannot
show a faster one, so breathing above half the heart rate is out of reach.
The lowest reportable rate is the bottom of the band (4 breaths/min, two
breaths in a 32 s window).
"""
import math
from dataclasses import dataclass
import numpy as np
from .core import CONFIG, PT, NNSeries, Result
from .hrv_freq import lomb_scargle, band_grid

CFG = CONFIG["breathing"]
_D = PT.CONFIG["detector"]


@dataclass(frozen=True)
class Modulations:
    beat_t: np.ndarray      # every detected beat, s
    rsa_t: np.ndarray; rsa_v: np.ndarray        # accepted NN intervals (ms) at their end beat
    amp_t: np.ndarray; amp_v: np.ndarray        # R amplitude (signal units) at unflagged beats


def r_amplitudes(y, beats, fs, mode=None, flagged=None):
    """R amplitude per beat, NaN where the beat is flagged or its window is
    not inside the signal. The window is the detector's own (R_BEFORE_S before
    to R_AFTER_S after the 5-15 Hz peak).
      'baseline'      height of the tp2 peak above the straight line through
                      the window's ends, with the parabolic vertex correction
      'peak_to_peak'  max - min of the window (R to S on a normal beat)
    flagged=True (peak_to_peak only) also measures flagged beats: max - min
    needs neither the beat's polarity nor its tp2 position, which is what a
    flag says is unknown."""
    mode = mode or CFG["amp_mode"]
    flagged = CFG["amp_flagged"] if flagged is None else flagged
    use_flagged = bool(flagged) and mode == "peak_to_peak"
    lo, hi = int(_D["R_BEFORE_S"] * fs), int(_D["R_AFTER_S"] * fs)
    y = np.asarray(y, dtype=float)
    out = np.full(len(beats), np.nan)
    for i, b in enumerate(beats):
        d = int(b["bp"])
        if (b["flagged"] and not use_flagged) or d - lo < 0 or d + hi >= len(y):
            continue
        w = y[d - lo:d + hi + 1]
        if mode == "peak_to_peak":
            out[i] = float(w.max() - w.min()); continue
        n = len(w)
        e0, e1 = w[:3].mean(), w[-3:].mean()
        wd = w - (e0 + (e1 - e0) * np.arange(n) / (n - 1))
        k = min(max(int(round(b["pos"])) - (d - lo), 1), n - 2)
        a, c = wd[k - 1], wd[k + 1]
        den = a - 2.0 * wd[k] + c
        out[i] = float(wd[k] - ((a - c) ** 2 / (8.0 * den) if den != 0.0 and abs(a - c) <= abs(den) else 0.0))
    return out


def modulations(y, beats, fs, amp_mode=None, amp_flagged=None):
    """Both per-beat series from a filtered ECG and the detector's beats."""
    nn = NNSeries.from_beats(beats, fs)
    amp = r_amplitudes(y, beats, fs, amp_mode, amp_flagged)
    ok = np.isfinite(amp)
    return Modulations(nn.beat_t, nn.times, nn.values, nn.beat_t[ok], amp[ok])


def _spectrum(t, v, t0, t1, n_all, f, cfg):
    """Normalised spectrum of one series in [t0, t1) on grid f, or a reason."""
    sel = (t >= t0) & (t < t1)
    t, v = t[sel], v[sel]
    if len(v) >= 3 and cfg["outlier_mad"]:
        med = np.median(v); mad = 1.4826 * np.median(np.abs(v - med))
        if mad > 0:
            keep = np.abs(v - med) <= cfg["outlier_mad"] * mad
            t, v = t[keep], v[keep]
    if len(v) < cfg["min_beats"]:
        return None, f"{len(v)} usable beats in the window, needs {cfg['min_beats']}", len(v)
    if n_all and len(v) / n_all < cfg["min_beat_coverage"]:
        return None, (f"{100 * len(v) / n_all:.0f}% of the window's beats usable, "
                      f"needs {100 * cfg['min_beat_coverage']:.0f}%"), len(v)
    v = v - np.polyval(np.polyfit(t - t0, v, 1), t - t0)
    p = lomb_scargle(t, v, f)
    s = float(p.sum())
    if not s > 0:
        return None, "no variation in the series", len(v)
    return p / s, None, len(v)


def _peak(f, p, halfwidth_hz):
    """(frequency, share of band power within halfwidth of it), or None when
    the maximum sits on a band edge."""
    k = int(np.argmax(p))
    if k == 0 or k == len(p) - 1:
        return None
    a, b, c = p[k - 1], p[k], p[k + 1]
    den = a - 2.0 * b + c
    fp = f[k] + (0.5 * (a - c) / den if den < 0 else 0.0) * (f[1] - f[0])
    return float(fp), float(p[np.abs(f - fp) <= halfwidth_hz].sum())


NAMES = {"rsa": "BR (RSA)", "ramp": "BR (R amplitude)", "fused": "BR (fused)"}


def window_spectra(mods, t0, t1, cfg=None):
    """The two normalised spectra of one window.
    Returns dict(W, n_beats, f, why, rsa=(p or None, why, n), ramp=(...));
    `why` is set, and f is None, when the window as a whole cannot be used."""
    cfg = {**CFG, **(cfg or {})}
    W = t1 - t0
    bt = mods.beat_t[(mods.beat_t >= t0) & (mods.beat_t < t1)]
    sp = dict(W=W, n_beats=len(bt), f=None, why=None, rsa=(None, None, 0), ramp=(None, None, 0))
    if W < cfg["window_s"] - 1e-9:
        sp["why"] = f"window {W:g} s, needs {cfg['window_s']:g} s"; return sp
    if len(bt) < cfg["min_beats"]:
        sp["why"] = f"{len(bt)} beats in the window, needs {cfg['min_beats']}"; return sp
    nyq = 0.5 * (len(bt) - 1) / float(bt[-1] - bt[0])
    f_lo, f_hi = cfg["band_bpm"][0] / 60.0, min(cfg["band_bpm"][1] / 60.0, nyq)
    if f_hi <= f_lo:
        sp["why"] = "heart rate too low for the breathing band"; return sp
    sp["f"] = f = band_grid(f_lo, f_hi, W, cfg["lomb_oversample"])
    sp["rsa"] = _spectrum(mods.rsa_t, mods.rsa_v, t0, t1, len(bt) - 1, f, cfg)
    sp["ramp"] = _spectrum(mods.amp_t, mods.amp_v, t0, t1, len(bt), f, cfg)
    return sp


def rate_from_spectra(sp, cfg=None):
    """{'rsa', 'ramp', 'fused'} -> Result (breaths/min) from window_spectra()."""
    cfg = {**CFG, **(cfg or {})}
    W, n_beats, f = sp["W"], sp["n_beats"], sp["f"]

    def out(key, value=None, why=None, n=0, **extra):
        return Result(NAMES[key], value, "breaths/min", why, int(n), W, W,
                      n / n_beats if n_beats else 0.0, extra)

    if f is None:
        return {k: out(k, why=sp["why"]) for k in NAMES}
    hw = cfg["share_halfwidth_cycles"] / W
    smin = cfg["peak_share_min"]

    def gated(key, p, n, **extra):
        pk = _peak(f, p, hw)
        if pk is None:
            return out(key, why="no peak inside the breathing band", n=n, **extra), None
        if pk[1] < smin:
            return out(key, why=f"peak holds {100 * pk[1]:.0f}% of band power, needs {100 * smin:.0f}%",
                       n=n, share=pk[1], **extra), None
        return out(key, 60.0 * pk[0], n=n, share=pk[1], **extra), pk

    res, good = {}, {}
    for key in ("rsa", "ramp"):
        p, why, n = sp[key]
        if p is None:
            res[key] = out(key, why=why, n=n); continue
        res[key], pk = gated(key, p, n)
        if pk is not None:
            good[key] = (p, n, pk)
    have = {k: sp[k] for k in ("rsa", "ramp") if sp[k][0] is not None}
    n_max = max([v[2] for v in have.values()], default=0)
    rule = cfg["fusion"]
    if not have:
        res["fused"] = out("fused", why="neither modulation has enough usable beats")
    elif rule == "product":
        if len(have) == 2:
            p = have["rsa"][0] * have["ramp"][0]
            s = float(p.sum())
            res["fused"] = (gated("fused", p / s, n_max, n_spectra=2)[0] if s > 0
                            else out("fused", why="the two spectra share no power", n=n_max))
        else:
            (k, (p, _, n)), = have.items()
            res["fused"] = gated("fused", p, n, n_spectra=1)[0]
    elif not good:
        res["fused"] = out("fused", why="neither modulation gave a usable peak", n=n_max)
    elif rule == "average":
        res["fused"] = gated("fused", np.mean([g[0] for g in good.values()], axis=0),
                             max(g[1] for g in good.values()), n_spectra=len(good))[0]
    elif rule == "best_share":
        k = max(good, key=lambda q: good[q][2][1])
        res["fused"] = out("fused", 60.0 * good[k][2][0], n=good[k][1], share=good[k][2][1], n_spectra=1)
    elif rule == "agree":
        if len(good) < 2:
            res["fused"] = out("fused", why="only one modulation gave a usable peak", n=n_max)
        else:
            a, b = 60.0 * good["rsa"][2][0], 60.0 * good["ramp"][2][0]
            if abs(a - b) > cfg["agree_bpm"]:
                res["fused"] = out("fused", why=f"the two modulations disagree ({a:.1f} and {b:.1f} breaths/min)", n=n_max)
            else:
                res["fused"] = out("fused", 0.5 * (a + b), n=n_max, n_spectra=2,
                                   share=min(good["rsa"][2][1], good["ramp"][2][1]))
    elif rule == "agree_or_ramp":
        a = 60.0 * good["rsa"][2][0] if "rsa" in good else None
        b = 60.0 * good["ramp"][2][0] if "ramp" in good else None
        if a is not None and b is not None and abs(a - b) <= cfg["agree_bpm"]:
            res["fused"] = out("fused", 0.5 * (a + b), n=n_max, n_spectra=2,
                               share=min(good["rsa"][2][1], good["ramp"][2][1]))
        elif b is not None and good["ramp"][2][1] >= cfg["ramp_alone_share"]:
            res["fused"] = out("fused", b, n=good["ramp"][1], n_spectra=1, share=good["ramp"][2][1])
        elif a is not None and b is not None:
            res["fused"] = out("fused", why=f"the two modulations disagree ({a:.1f} and {b:.1f} breaths/min) and the "
                               f"R-amplitude peak is under {100 * cfg['ramp_alone_share']:.0f}%", n=n_max)
        else:
            res["fused"] = out("fused", why="no agreement between the modulations and no strong R-amplitude peak", n=n_max)
    else:
        raise ValueError(f"unknown fusion rule {rule!r}")
    return res


def breathing_rate(mods, t0, t1, cfg=None):
    """{'rsa', 'ramp', 'fused'} -> Result (breaths/min) for the window [t0, t1).
    Result.extra['share'] is the peak's share of band power."""
    return rate_from_spectra(window_spectra(mods, t0, t1, cfg), cfg)
