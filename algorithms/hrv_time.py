"""Time-domain HRV on an NNSeries: RMSSD, SDNN, pNN50.

Definitions (Task Force 1996 names), with holes handled explicitly:

  SDNN   standard deviation (n-1) of the accepted NN intervals, ms. It grows
         with the length of the window, so an SDNN is only comparable with
         another one from the same duration: Result.valid_s travels with it.
  RMSSD  root mean square of the differences between SUCCESSIVE accepted
         intervals, ms. Same value as pan_tompkins.rmssd_nn on the same series;
         the minimum window here is stricter (60 s as well as 30 intervals).
  pNN50  share of those successive differences larger than 50 ms, in percent of
         the number of differences. neurokit2 divides by the number of
         intervals instead (differences + 1); with holes only the number of
         differences is well defined.
"""
import numpy as np
from .core import gate, minimum, result


def rmssd(nn):
    why = gate(nn, "rmssd")
    a, b = nn.pairs()
    if why is None and len(a) < minimum("rmssd")["pairs"]:
        why = f"{len(a)} successive differences, needs {minimum('rmssd')['pairs']}"
    if why:
        return result(nn, "RMSSD", "ms", withheld=why, n_used=len(a))
    return result(nn, "RMSSD", "ms", float(np.sqrt(np.mean((b - a) ** 2))), n_used=len(a))


def sdnn(nn):
    why = gate(nn, "sdnn")
    v = nn.values
    if why:
        return result(nn, "SDNN", "ms", withheld=why, n_used=len(v))
    return result(nn, "SDNN", "ms", float(np.std(v, ddof=1)), n_used=len(v))


def pnn50(nn):
    why = gate(nn, "pnn50")
    a, b = nn.pairs()
    if why is None and len(a) < minimum("pnn50")["pairs"]:
        why = f"{len(a)} successive differences, needs {minimum('pnn50')['pairs']}"
    if why:
        return result(nn, "pNN50", "%", withheld=why, n_used=len(a))
    return result(nn, "pNN50", "%", 100.0 * float(np.mean(np.abs(b - a) > 50.0)), n_used=len(a))


def time_domain(nn):
    return {"rmssd": rmssd(nn), "sdnn": sdnn(nn), "pnn50": pnn50(nn)}
