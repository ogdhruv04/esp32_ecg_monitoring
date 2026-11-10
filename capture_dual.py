#!/usr/bin/env python3
"""Record both devices at once, into two aligned CSV files.

    ./capture_dual.py --seconds 120 --label rest01

One thread per port so a stall on one link cannot delay the other. Each row
carries the host clock time the line arrived, which is coarse (tens of ms,
jittered by USB scheduling) but enough to establish which device started first.
The fine alignment comes later from the beat trains themselves.

Each board's '#' diagnostic lines go to a sidecar <stamp>_<label>_<board>.log
with their host time. Among them is the firmware's "# cfg emux:.. cal:.. mode:.."
line (every 5 s and on every change), so the log records the input
configuration each CSV was captured in.

A board with the extra sensors (the reference board) also sends PPG, IMU,
temperature and GSR lines. Each stream is saved to its own CSV beside that
board's ECG file: <stamp>_<label>_ref_ppg.csv, _imu.csv, _temp.csv, _gsr.csv
(formats in sensor_streams.py), with the same host_time column. integrity.py
finds and checks them when given the ECG CSVs.
"""
import argparse, datetime, pathlib, threading, time
import serial
from sensor_streams import LineReader, SensorWriter

ap = argparse.ArgumentParser()
ap.add_argument("--ring", default="/dev/ttyACM0")
ap.add_argument("--ref",  default="/dev/ttyUSB0")
ap.add_argument("--ring-baud", type=int, default=460800)
ap.add_argument("--ref-baud",  type=int, default=460800)
ap.add_argument("--seconds", type=float, default=120.0)
ap.add_argument("--label", default="dual")
args = ap.parse_args()

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
outdir = pathlib.Path("captures"); outdir.mkdir(exist_ok=True)
stop = threading.Event()
results = {}

def worker(name, port, baud):
    path = outdir / f"{stamp}_{args.label}_{name}.csv"
    logp = path.with_suffix(".log")
    n = bad = 0
    first_host = last_host = None
    sens = SensorWriter(path, host_time=True)
    try:
        s = serial.Serial(port, baud, timeout=1)
        s.dtr = True; s.rts = False
        s.reset_input_buffer()
        port = LineReader(s)
    except Exception as e:
        results[name] = f"ERROR opening {port}: {e}"
        return
    with path.open("w") as f, logp.open("w") as lf:
        f.write("host_time,index,isr_micros,value,etag,leadoff\n")
        while not stop.is_set():
            ln = port.readline().decode(errors="replace").strip()
            if not ln:
                continue
            if ln.startswith("#"):
                lf.write(f"{time.time():.6f} {ln}\n")
                continue
            if ln.startswith("S,"):
                p = ln[2:].split(",")
                if len(p) != 5:
                    bad += 1; continue
                t = time.time()
                if first_host is None: first_host = t
                last_host = t
                f.write(f"{t:.6f},{','.join(p)}\n")
                n += 1
                continue
            sens.handle(ln, time.time())
    s.close()
    sens.close()
    results[name] = (path, n, bad, first_host, last_host, sens.summary())

threads = [threading.Thread(target=worker, args=a, daemon=True)
           for a in (("ring", args.ring, args.ring_baud),
                     ("ref",  args.ref,  args.ref_baud))]
print(f"Recording {args.seconds:.0f}s from both devices.")
print("Hold still. Chest electrodes on, fingers on the ring pads.\n")
for t in threads: t.start()
try:
    time.sleep(args.seconds)
except KeyboardInterrupt:
    print("\ninterrupted")
stop.set()
for t in threads: t.join(timeout=3)

print()
for name in ("ring", "ref"):
    r = results.get(name)
    if isinstance(r, str):
        print(f"  {name:5}: {r}"); continue
    if r is None:
        print(f"  {name:5}: no data"); continue
    path, n, bad, first, last, sens_lines = r
    # Rate over the span actually recorded, not the span requested: threads
    # start and stop a little inside the window, and dividing by the requested
    # duration understates the rate by a few percent - which reads as a defect.
    el = (last - first) if (first and last and last > first) else args.seconds
    print(f"  {name:5}: {n:6d} samples ({n/el:.1f}/s over {el:.1f}s), {bad} malformed -> {path.name}")
    for sl in sens_lines:
        print(f"         {sl}")
both = [results.get(k) for k in ("ring","ref")]
if all(isinstance(x, tuple) for x in both) and all(x[3] for x in both):
    print(f"\n  host-clock start offset: {abs(both[0][3]-both[1][3])*1000:.0f} ms"
          f"  (coarse - fine alignment comes from the beat trains)")
