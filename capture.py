#!/usr/bin/env python3
"""Record an ECG session to a CSV file and report the Week-1 gate numbers.

    ./capture.py --seconds 300 --label rest_dhruv_01

Writes captures/<timestamp>_<label>.csv with one row per sample, plus a
sidecar .log holding the firmware's '#' diagnostic lines. The CSV is the
research artifact; the log is the evidence that the CSV can be trusted.
"""
import argparse, datetime, pathlib, sys, time
import serial

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/ttyACM0")
ap.add_argument("--baud", type=int, default=57600)
ap.add_argument("--seconds", type=float, default=300.0)
ap.add_argument("--label", default="capture")
ap.add_argument("--sps", type=int, default=256, help="expected sample rate")
args = ap.parse_args()

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
out = pathlib.Path("captures") / f"{stamp}_{args.label}.csv"
logp = out.with_suffix(".log")
out.parent.mkdir(exist_ok=True)

ser = serial.Serial(args.port, args.baud, timeout=1)
ser.dtr = True
ser.rts = False
ser.reset_input_buffer()

n_samples = n_bad = 0
first_idx = last_idx = None
first_us = last_us = None
t0 = time.time()

print(f"Recording {args.seconds:.0f}s to {out}")
print("Sit still, hands relaxed, breathe normally.\n")

with out.open("w") as f, logp.open("w") as lf:
    f.write("index,isr_micros,value,etag,leadoff\n")
    try:
        while time.time() - t0 < args.seconds:
            raw = ser.readline().decode(errors="replace").strip()
            if not raw:
                continue
            if raw.startswith("S,"):
                parts = raw[2:].split(",")
                if len(parts) != 5:
                    n_bad += 1
                    continue
                f.write(",".join(parts) + "\n")
                idx, us = int(parts[0]), int(parts[1])
                if first_idx is None:
                    first_idx, first_us = idx, us
                last_us = us
                last_idx = idx
                n_samples += 1
            else:
                lf.write(raw + "\n")
                lf.flush()
                # Surface firmware diagnostics live; they are the gate evidence.
                if raw.startswith("#"):
                    el = time.time() - t0
                    print(f"[{el:6.1f}s] {raw}")
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        ser.close()

elapsed = time.time() - t0
print(f"\n--- {out} ---")
print(f"  wall time      : {elapsed:.1f} s")
print(f"  samples written: {n_samples}")
print(f"  malformed lines: {n_bad}")
if first_idx is not None:
    span = last_idx - first_idx + 1
    missing = span - n_samples
    print(f"  index span     : {first_idx}..{last_idx} ({span})")
    # A gap in the monotonic index means the firmware produced a sample that
    # never reached this file - dropped by USB-CDC backpressure, not by the
    # sensor. It corrupts exactly one RR interval, so it has to be counted.
    print(f"  index gaps     : {missing} ({100*missing/span:.3f}% of span)")
    # Rate from the device's own clock, not wall time: the wall-clock figure is
    # skewed by however long the port took to open relative to t0, which made an
    # otherwise-clean 256 SPS look like 248 or 267 depending on the run.
    if first_us is not None and last_us > first_us:
        dev_span_s = (last_us - first_us) / 1e6
        print(f"  device rate    : {(span - 1)/dev_span_s:.2f} SPS (expected {args.sps})")
    print(f"  wall-clock rate: {n_samples/elapsed:.2f} SPS (includes port-open latency)")
