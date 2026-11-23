#!/usr/bin/env python3
"""Integrity of capture CSVs, judged on the host (CLAUDE.md rule): index
continuity, duplicates, malformed rows. Saves analysis/integrity_<stem>.txt.

    ./integrity.py captures/<stamp>_<label>_ring.csv captures/<stamp>_<label>_ref.csv

Give it the ECG CSVs only. For each one it also looks for the extra-sensor
files the capture tools write beside it (<ecg stem>_ppg.csv, _imu.csv,
_temp.csv, _gsr.csv; see sensor_streams.py) and checks each that exists:

  counter      the stream's own sequence number: missing, repeated, backward.
               A hole is a line lost between the firmware and this file.
  ecg_index    the ECG-clock timestamp: never backward, inside the ECG file's
               range, and (IMU, GSR, temperature) advancing by the scheduled
               step. A step one or two samples off is a FIFO drain that held 5
               samples instead of 4, which is normal. A step of twice the
               schedule or more at an unbroken counter is a reading the
               firmware skipped because it was busy - not a lost line.
  lag          micros of the reading minus isr_micros of the ECG sample it is
               stamped with. Both are the same ESP32 clock, so this checks the
               timestamp itself: it should be a few ms and never negative.
  rate         readings per second of ECG-index time. For the PPG this is the
               MAX30102's sample clock measured against the MAX30003's.
  values       range checks that catch a dead or saturated sensor. They say
               nothing about whether the signal is physiological.

The firmware's own counters (the last '# sens:' line of the capture's .log)
are printed under the host figures for comparison, never instead of them.
"""
import pathlib, sys, io, contextlib
import numpy as np
from sensor_streams import (STREAMS, EVERY, ECG_SPS, PPG_SPS, GSR_OVERSAMPLE, sidecar,
                            ACCEL_LSB_PER_G, GYRO_LSB_PER_DPS, TEMP_C_PER_LSB, PPG_FULL_SCALE)


def check(path):
    lines = pathlib.Path(path).read_text().splitlines()
    head, rows = lines[0].split(","), lines[1:]
    ok = [r.split(",") for r in rows if len(r.split(",")) == len(head)]
    malformed = len(rows) - len(ok)
    col = {h: i for i, h in enumerate(head)}
    idx = np.array([int(r[col["index"]]) for r in ok], dtype=np.int64)
    d = np.diff(idx)
    missing = int(np.sum(d[d > 1] - 1))
    print(f"{pathlib.Path(path).name}")
    print(f"  rows {len(rows)}  malformed {malformed}  index {idx[0]}..{idx[-1]} "
          f"(span {idx[-1]-idx[0]+1})")
    print(f"  missing {missing}  gaps {int(np.sum(d > 1))}  duplicates {int(np.sum(d == 0))}  "
          f"backward jumps {int(np.sum(d < 0))}")
    if "host_time" in col:
        t = np.array([float(r[col["host_time"]]) for r in ok])
        print(f"  {len(ok)} samples over {t[-1]-t[0]:.2f} s host time = {(len(ok)-1)/(t[-1]-t[0]):.2f} SPS")
    # index -> isr_micros, for the sensor timestamp check below
    us = [int(r[col["isr_micros"]]) for r in ok]
    return dict(zip(idx.tolist(), us)), int(idx.min()), int(idx.max())


def read_sensor(path):
    """-> (columns without host_time, int64 array of the usable rows, malformed, total)."""
    lines = pathlib.Path(path).read_text().splitlines()
    head, rows = lines[0].split(","), lines[1:]
    keep = [i for i, h in enumerate(head) if h != "host_time"]
    ok = []
    for r in rows:
        p = r.split(",")
        if len(p) != len(head):
            continue
        try:
            ok.append([int(p[i]) for i in keep])
        except ValueError:
            continue
    a = np.array(ok, dtype=np.int64).reshape(len(ok), len(keep))
    return [head[i] for i in keep], a, len(rows) - len(ok), len(rows)


def check_sensor(name, path, ecg_us, ecg_first, ecg_last):
    names, a, malformed, total = read_sensor(path)
    print(f"  {pathlib.Path(path).name}")
    if not len(a):
        print(f"    rows {total}  malformed {malformed}  NO USABLE ROWS")
        return
    c = {n: a[:, i] for i, n in enumerate(names)}
    counter = names[0]
    seq, eidx, us = c[counter], c["ecg_index"], c["micros"]

    d = np.diff(seq)
    print(f"    rows {total}  malformed {malformed}  {counter} {seq[0]}..{seq[-1]} "
          f"(span {seq[-1]-seq[0]+1})")
    print(f"    missing {int(np.sum(d[d > 1] - 1))}  gaps {int(np.sum(d > 1))}  "
          f"repeated {int(np.sum(d == 0))}  backward jumps {int(np.sum(d < 0))}")

    # ECG-clock timestamps
    de = np.diff(eidx)
    outside = int(np.sum((eidx < ecg_first) | (eidx > ecg_last)))
    print(f"    ecg_index {eidx[0]}..{eidx[-1]}  backward {int(np.sum(de < 0))}  "
          f"outside the ECG file's range {outside}")
    if name in EVERY:
        step = EVERY[name]
        adj = de[d == 1]                       # only between consecutive readings
        if adj.size:
            print(f"    ecg_index step between consecutive readings: {step} (scheduled) on "
                  f"{100*np.mean(adj == step):.2f}%, largest {int(adj.max())}, "
                  f"skipped readings (step >= {2*step}) {int(np.sum(adj >= 2*step))}")
    else:
        # samples fetched per poll: rows sharing one (ecg_index, micros) stamp
        _, per_poll = np.unique(np.stack([eidx, us], 1), axis=0, return_counts=True)
        print(f"    samples per poll: median {int(np.median(per_poll))}, "
              f"largest {int(per_poll.max())} (the MAX30102 FIFO holds 32)")

    # the timestamp itself: the reading's micros against its ECG sample's isr_micros
    ref = np.array([ecg_us.get(int(i), -1) for i in eidx], dtype=np.int64)
    have = ref >= 0
    if have.any():
        lag = ((us[have] - ref[have] + 2**31) % 2**32 - 2**31) / 1000.0     # ms, wrap-safe
        print(f"    lag behind the stamped ECG sample's interrupt: median {np.median(lag):.2f} ms, "
              f"99th pct {np.percentile(lag, 99):.2f} ms, max {lag.max():.2f} ms, "
              f"negative {int(np.sum(lag < 0))}")
    print(f"    rows stamped with an ECG index that is not in the ECG file: {int(np.sum(~have))}")

    span_s = (eidx[-1] - eidx[0]) / ECG_SPS
    if span_s > 0:
        rate = (seq[-1] - seq[0]) / span_s
        nominal = PPG_SPS if name == "ppg" else ECG_SPS / EVERY[name]
        print(f"    rate {rate:.3f} per second of ECG-index time over {span_s:.1f} s "
              f"(nominal {nominal:g}; each end is quantised to one FIFO drain)")

    # values: dead or saturated?
    if name == "ppg":
        for ch in ("red", "ir"):
            v = c[ch]
            print(f"    {ch:3}: {v.min()}..{v.max()}  median {int(np.median(v))}  "
                  f"at full scale ({PPG_FULL_SCALE}) {int(np.sum(v >= PPG_FULL_SCALE))}  "
                  f"zero {int(np.sum(v == 0))}")
    elif name == "imu":
        raw = np.stack([c[n] for n in ("ax", "ay", "az", "gx", "gy", "gz")], 1)
        mag = np.linalg.norm(raw[:, :3] / ACCEL_LSB_PER_G, axis=1)
        rot = np.linalg.norm(raw[:, 3:] / GYRO_LSB_PER_DPS, axis=1)
        print(f"    |accel| median {np.median(mag):.3f} g (1 g expected at rest), "
              f"range {mag.min():.3f}..{mag.max():.3f} g; |gyro| median {np.median(rot):.2f} deg/s")
        print(f"    values at the int16 rail {int(np.sum((raw <= -32768) | (raw >= 32767)))}  "
              f"all-zero rows {int(np.sum(~raw.any(axis=1)))}")
    elif name == "temp":
        t = c["raw"] * TEMP_C_PER_LSB
        print(f"    temperature {t.min():.3f}..{t.max():.3f} degC  median {np.median(t):.3f}  "
              f"exactly zero {int(np.sum(c['raw'] == 0))}")
    elif name == "gsr":
        mv = c["mv_sum"] / GSR_OVERSAMPLE
        raw = c["adc_sum"] / GSR_OVERSAMPLE
        print(f"    output {mv.min():.1f}..{mv.max():.1f} mV  median {np.median(mv):.1f} mV; "
              f"raw ADC {raw.min():.0f}..{raw.max():.0f} of 4095, "
              f"at 0: {int(np.sum(raw <= 0))}, at 4095: {int(np.sum(raw >= 4095))}")


def firmware_view(ecg_csv):
    """What the firmware itself reported, for comparison with the host figures."""
    logp = pathlib.Path(ecg_csv).with_suffix(".log")
    if not logp.exists():
        return
    lines = [ln[ln.index("# sens"):] for ln in logp.read_text(errors="replace").splitlines()
             if "# sens" in ln]
    stats = [ln for ln in lines if ln.startswith("# sens: i2c:")]
    events = [ln for ln in lines if any(k in ln for k in ("DISABLED", "FIFO overflow", "(set)",
                                                           "probing again", "NOT USED", "no answer"))]
    if stats:
        print(f"  firmware's last counter line ({logp.name}):")
        print(f"    {stats[-1]}")
    if events:
        print(f"  firmware sensor events in the log: {len(events)}")
        for ln in events[:12]:
            print(f"    {ln}")


if __name__ == "__main__":
    paths = sys.argv[1:]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for p in paths:
            ecg_us, first, last = check(p)
            found = False
            for name, _ in STREAMS.values():
                sp = sidecar(p, name)
                if sp.exists():
                    found = True
                    check_sensor(name, sp, ecg_us, first, last)
            if found:
                firmware_view(p)
    print(buf.getvalue(), end="")
    stem = pathlib.Path(paths[0]).stem.rsplit("_", 1)[0]
    out = pathlib.Path("analysis") / f"integrity_{stem}.txt"
    out.write_text(f"# ./integrity.py {' '.join(paths)}\n" + buf.getvalue())
    print(f"saved {out}")
