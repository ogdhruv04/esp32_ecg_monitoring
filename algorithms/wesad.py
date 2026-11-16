"""WESAD loader (docs/wesad_plan.md, sections 2 and 3).

    extract(zip_path, out_dir, "S2")     # SX.pkl -> out_dir/S2.npz, the channels we use
    rec = load(out_dir, "S2")            # a Recording
    rec.segments()                       # {"baseline": (t0, t1), "stress": ..., ...}
    windows(rec.parts())                 # the 180 s windows of the plan

SX.pkl is a Python 2 pickle of nested dicts of numpy arrays. A pickle can run
code when it is loaded, and this one is a download, so it is read with an
unpickler that only builds numpy arrays and refuses everything else.

Time is seconds from the RespiBAN's first sample; the labels share that start
(readme II). The wrist arrays in SX.pkl were aligned to it by the authors, by
hand, from a double-tap (plan section 2): wrist sample k is taken to be at
k / fs. Nothing here corrects that alignment.
"""
import io, os, pickle, zipfile
from dataclasses import dataclass
import numpy as np
from .core import CONFIG

W = CONFIG["wesad"]
FS = W["fs"]                                   # chest 700; wrist bvp 64, eda 4, temp 4
LABELS = {int(k): v for k, v in W["labels"].items()}
SUBJECTS = W["subjects"]

_ALLOWED = {
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
    ("_codecs", "encode"),                     # how Python 2 byte strings arrive under latin1
}


class _ArraysOnly(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) not in _ALLOWED:
            raise pickle.UnpicklingError(f"refusing {module}.{name}: only numpy arrays are loaded from a WESAD pickle")
        return super().find_class(module, name)


def read_pkl(f):
    """The dict in SX.pkl, from a path or an open binary file."""
    if isinstance(f, (str, os.PathLike)):
        with open(f, "rb") as fh:
            return _ArraysOnly(fh, encoding="latin1").load()
    return _ArraysOnly(f, encoding="latin1").load()


@dataclass(frozen=True)
class Recording:
    subject: str
    label: np.ndarray            # uint8, one per chest sample (700 Hz)
    ecg: np.ndarray              # chest, mV, 700 Hz
    eda_chest: np.ndarray        # uS, 700 Hz
    temp_chest: np.ndarray       # deg C, 700 Hz
    bvp: np.ndarray              # wrist, device units, 64 Hz
    eda_wrist: np.ndarray        # uS, 4 Hz
    temp_wrist: np.ndarray       # deg C, 4 Hz

    @property
    def duration_s(self):
        return len(self.label) / FS["chest"]

    def durations(self):
        """Length of every stream in seconds; they should agree if the authors'
        alignment trimmed both devices to the same span."""
        return {"chest": len(self.ecg) / FS["chest"], "label": len(self.label) / FS["chest"],
                "bvp": len(self.bvp) / FS["bvp"], "eda_wrist": len(self.eda_wrist) / FS["eda"],
                "temp_wrist": len(self.temp_wrist) / FS["temp"]}

    def runs(self):
        """Every run of consecutive equal labels: (label, t0, t1), in order."""
        return label_runs(self.label, FS["chest"])

    def segments(self):
        return segments(self.runs())

    def parts(self):
        return parts(self.segments())

    def order(self):
        """'stress_first' or 'amusement_first', from the label sequence."""
        s = self.segments()
        return "stress_first" if s["stress"][0] < s["amusement"][0] else "amusement_first"


def label_runs(label, fs):
    label = np.asarray(label)
    edges = np.flatnonzero(np.diff(label)) + 1
    starts = np.concatenate([[0], edges]); ends = np.concatenate([edges, [len(label)]])
    return [(int(label[a]), a / fs, b / fs) for a, b in zip(starts, ends)]


def segments(runs):
    """The condition segments of the plan: the longest run of labels 1, 2, 3,
    and every run of label 4 (meditation_1, meditation_2 in time order)."""
    out = {}
    for code in (1, 2, 3):
        mine = [(t0, t1) for c, t0, t1 in runs if c == code]
        if not mine:
            raise ValueError(f"no samples labelled {code} ({LABELS[code]})")
        out[LABELS[code]] = max(mine, key=lambda r: r[1] - r[0])
    for i, (t0, t1) in enumerate([(t0, t1) for c, t0, t1 in runs if c == 4], 1):
        out[f"meditation_{i}"] = (t0, t1)
    return out


def parts(segs):
    """Segments with the baseline cut at its midpoint: the first half is the
    subject's reference (never classified), the second half the baseline class."""
    b0, b1 = segs["baseline"]
    mid = b0 + (b1 - b0) / 2.0
    out = {"reference": (b0, mid), "baseline": (mid, b1)}
    out.update({k: v for k, v in segs.items() if k != "baseline"})
    return out


def windows(parts_, window_s=None, step_s=None):
    """[(part, t0, t1)]: windows of window_s starting every step_s from the
    start of each part, each entirely inside it."""
    w = W["window_s"] if window_s is None else window_s
    step = W["step_s"] if step_s is None else step_s
    out = []
    for name, (a, b) in parts_.items():
        k = 0
        while a + k * step + w <= b + 1e-9:
            out.append((name, a + k * step, a + k * step + w)); k += 1
    return out


# ----------------------------------------------------------------- files
def _col(a):
    a = np.asarray(a)
    return a[:, 0] if a.ndim == 2 and a.shape[1] == 1 else a


def from_dict(d):
    """A Recording from the dict in SX.pkl (keys may be str or bytes)."""
    def get(m, key):
        return m[key] if key in m else m[key.encode()]
    sig = get(d, "signal"); chest = get(sig, "chest"); wrist = get(sig, "wrist")
    subject = get(d, "subject")
    subject = subject.decode() if isinstance(subject, bytes) else str(subject)
    f32 = lambda a: np.ascontiguousarray(_col(a), dtype=np.float32)
    rec = Recording(subject, np.ascontiguousarray(_col(get(d, "label")), dtype=np.uint8),
                    f32(get(chest, "ECG")), f32(get(chest, "EDA")), f32(get(chest, "Temp")),
                    f32(get(wrist, "BVP")), f32(get(wrist, "EDA")), f32(get(wrist, "TEMP")))
    if len(rec.label) != len(rec.ecg):
        raise ValueError(f"{subject}: {len(rec.label)} labels for {len(rec.ecg)} chest samples")
    return rec


_FIELDS = ["label", "ecg", "eda_chest", "temp_chest", "bvp", "eda_wrist", "temp_wrist"]


def extract(zip_path, out_dir, subject):
    """SX.pkl inside WESAD.zip -> out_dir/SX.npz holding only the channels the
    plan uses (float32; about 60 MB instead of 1 GB). Returns the Recording."""
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z, z.open(f"WESAD/{subject}/{subject}.pkl") as f:
        rec = from_dict(read_pkl(io.BufferedReader(f, 1 << 20)))
    if rec.subject != subject:
        raise ValueError(f"{subject}.pkl says it is {rec.subject}")
    tmp = os.path.join(out_dir, f".{subject}.tmp.npz")
    np.savez(tmp, **{k: getattr(rec, k) for k in _FIELDS})
    os.replace(tmp, os.path.join(out_dir, f"{subject}.npz"))
    return rec


def load(cache_dir, subject):
    with np.load(os.path.join(cache_dir, f"{subject}.npz")) as z:
        return Recording(subject, *[z[k] for k in _FIELDS])
