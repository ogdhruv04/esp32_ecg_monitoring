"""ECG samples -> the detector's beats, the same way for every validation script.

The filter is the monitoring chain (EcgFilter.kt): 0.5 Hz high-pass, mains
notch, 40 Hz low-pass. causal=True is what the phone runs; False is the
zero-phase offline version used by benchmark_mitdb.py and agreement.py. Beat
positions are whatever pan_tompkins.PanTompkins reports with the parameters
frozen in tp2_config.json (tp3 from 13 Nov 2026; timing='tp2.1' gives the
previous timing point); nothing about detection is re-implemented here.
"""
import numpy as np
from scipy import signal as sps
from .core import PT

FS = 256.0          # our devices' sample rate; public data is resampled to it


def resample(x, fs_in, fs_out=FS):
    if fs_in == fs_out:
        return np.asarray(x, dtype=float)
    return sps.resample(np.asarray(x, dtype=float), int(round(len(x) * fs_out / fs_in)))


def filter_ecg(x, fs, mains, causal=False, harmonic=False):
    """0.5 Hz HP (4th order), mains notch (Q 30; its 2nd harmonic too when
    harmonic=True), 40 Hz LP (4th order)."""
    f2 = sps.sosfilt if causal else sps.sosfiltfilt
    f1 = sps.lfilter if causal else sps.filtfilt
    y = f2(sps.butter(4, 0.5, "highpass", fs=fs, output="sos"), x)
    for f in [mains] + ([2 * mains] if harmonic and 2 * mains < fs / 2 else []):
        b, a = sps.iirnotch(f, 30.0, fs=fs)
        y = f1(b, a, y)
    return f2(sps.butter(4, 40.0, "lowpass", fs=fs, output="sos"), y)


def detect(y, fs=FS, timing=None):
    """Run the detector over a filtered signal; returns its `beats` list
    (dicts with pos, bp, kind, flagged, gap)."""
    pt = PT.PanTompkins(fs, timing)
    for v in y:
        pt.process(v)
    return pt.beats
