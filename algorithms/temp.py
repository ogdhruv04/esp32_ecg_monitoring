"""Temperature slope (docs/wesad_plan.md, section 4.4).

One feature: the least-squares slope of the temperature over the window, in
degrees C per minute. It is withheld (NaN) when any sample of the window is
not finite or lies outside the plausible range in the config (sensor off the
skin). The temperature LEVEL is deliberately not a feature: skin under a device
keeps warming after it is put on, so the level mostly tells the time.
"""
import numpy as np
from .core import CONFIG

T = CONFIG["temp"]
FS = T["fs_hz"]


def slope(x_c, t0, t1, fs=FS):
    i0, i1 = int(np.ceil(t0 * fs - 1e-9)), int(np.ceil(t1 * fs - 1e-9))
    lo, hi = T["valid_range_c"]
    if i0 < 0 or i1 > len(x_c) or i1 - i0 < 2:
        return float("nan")
    x = np.asarray(x_c[i0:i1], dtype=float)
    if not np.all(np.isfinite(x)) or x.min() < lo or x.max() > hi:
        return float("nan")
    return float(np.polyfit(np.arange(len(x)) / fs / 60.0, x, 1)[0])
