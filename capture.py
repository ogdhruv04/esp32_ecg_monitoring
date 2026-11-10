#!/usr/bin/env python3
"""Record an ECG session to a CSV file and report the Week-1 gate numbers.

    ./capture.py --seconds 300 --label rest_dhruv_01
    ./capture.py --port /dev/ttyUSB0 --baud 460800 --label test01 --live

Writes captures/<timestamp>_<label>.csv with one row per sample, plus a
sidecar .log holding the firmware's '#' diagnostic lines. The CSV is the
research artifact; the log is the evidence that the CSV can be trusted.

--live also opens a scrolling plot while recording. It is display only: the
CSV is written exactly as without it, and closing the window ends the capture.
"""
import argparse, datetime, pathlib, queue, threading, time
import serial

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/ttyACM0")
ap.add_argument("--baud", type=int, default=57600)
ap.add_argument("--seconds", type=float, default=300.0)
ap.add_argument("--label", default="capture")
ap.add_argument("--sps", type=int, default=256, help="expected sample rate")
ap.add_argument("--live", action="store_true", help="show a live plot while recording")
ap.add_argument("--window", type=float, default=8.0, help="live plot width, seconds")
ap.add_argument("--mains", type=float, default=50.0, help="live plot notch frequency")
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
seen = set()
stop = threading.Event()
live_q = queue.Queue() if args.live else None
t0 = time.time()

print(f"Recording {args.seconds:.0f}s to {out}")
print("Sit still, hands relaxed, breathe normally.\n")

def record():
    global n_samples, n_bad, first_idx, last_idx, first_us, last_us
    with out.open("w") as f, logp.open("w") as lf:
        f.write("index,isr_micros,value,etag,leadoff\n")
        while time.time() - t0 < args.seconds and not stop.is_set():
            raw = ser.readline().decode(errors="replace").replace("\x00", "").strip()
            if not raw:
                continue
            if raw.startswith("S,"):
                parts = raw[2:].split(",")
                # Parse before writing. The WSL/usbip serial path has delivered
                # lines of NUL bytes and lines missing their head; one of those
                # crashed a capture 230 s into a 300 s run.
                try:
                    if len(parts) != 5:
                        raise ValueError
                    idx, us, val, _, _ = (int(p) for p in parts)
                except ValueError:
                    n_bad += 1
                    continue
                f.write(",".join(parts) + "\n")
                if first_idx is None:
                    first_idx, first_us = idx, us
                last_us = us
                last_idx = idx
                n_samples += 1
                seen.add(idx)
                if live_q is not None:
                    live_q.put((idx, val))
            else:
                lf.write(raw + "\n")
                lf.flush()
                # Surface firmware diagnostics live; they are the gate evidence.
                if raw.startswith("#"):
                    el = time.time() - t0
                    print(f"[{el:6.1f}s] {raw}")

def live_plot(reader):
    """Scrolling filtered trace with beat marks and heart rate.

    The filter is causal and mirrors EcgFilter.kt (0.5 Hz HP, mains + 2x mains
    notch at Q 30, 40 Hz LP), so it shows what the phone shows, not the
    zero-phase filtering analyze.py uses. Beats come from pan_tompkins.py, the
    reference for BeatDetector.kt. Neither result is saved.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    import scipy.signal as sps
    from matplotlib.animation import FuncAnimation
    from pan_tompkins import PanTompkins

    fs = args.sps
    sos = [sps.butter(4, 0.5, "highpass", fs=fs, output="sos"),
           sps.tf2sos(*sps.iirnotch(args.mains, 30.0, fs=fs))]
    if 2 * args.mains < fs / 2:
        sos.append(sps.tf2sos(*sps.iirnotch(2 * args.mains, 30.0, fs=fs)))
    sos.append(sps.butter(4, 40.0, "lowpass", fs=fs, output="sos"))
    sos = np.vstack(sos)
    zi = np.zeros((sos.shape[0], 2))

    n = int(args.window * fs)
    t = np.full(n, np.nan); y = np.full(n, np.nan)
    pt = PanTompkins(fs)
    beats = []
    st = {"zi": zi, "start": None, "last": None, "gaps": 0}

    fig, ax = plt.subplots(figsize=(12, 4))
    fig.canvas.manager.set_window_title(f"ECG live - {out.name}")
    line, = ax.plot([], [], lw=0.9, color="#1f6f8b")
    dots, = ax.plot([], [], "o", ms=5, color="#c0392b")
    ax.set_xlabel("time (s, from sample index)")
    ax.set_ylabel("filtered (ADC counts)")
    ax.grid(alpha=0.3)
    title = ax.set_title("")

    def update(_):
        nonlocal t, y
        chunk = []
        while True:
            try:
                chunk.append(live_q.get_nowait())
            except queue.Empty:
                break
        keep = []
        for idx, val in chunk:
            if st["last"] is not None:
                if idx <= st["last"]:
                    continue                    # repeated line from the serial path
                if idx > st["last"] + 1:
                    pt.skip(idx - st["last"] - 1)
                    st["gaps"] += 1
                    keep.append((idx - 0.5, np.nan))   # break the line at the hole
            else:
                st["start"] = idx
            st["last"] = idx
            keep.append((idx, val))
        if keep:
            ki = np.array([k[0] for k in keep]); kv = np.array([k[1] for k in keep], float)
            ok = ~np.isnan(kv)
            filt = np.full(len(kv), np.nan)
            filt[ok], st["zi"] = sps.sosfilt(sos, kv[ok], zi=st["zi"])
            for v in filt[ok]:
                b = pt.process(v)
                if b is not None:
                    beats.append(st["start"] + b)
            t = np.concatenate([t, ki / fs])[-n:]
            y = np.concatenate([y, filt])[-n:]
        line.set_data(t, y)
        if np.isfinite(t).any():
            lo, hi = np.nanmin(t), np.nanmax(t)
            ax.set_xlim(max(lo, hi - args.window), hi)
            vis = y[np.isfinite(y)]
            if vis.size:
                a, b = np.percentile(vis, [0.5, 99.5]); pad = 0.15 * (b - a + 1)
                ax.set_ylim(a - pad, b + pad)
            bt = np.array([bi for bi in beats if bi / fs >= hi - args.window], float)
            if bt.size:
                yi = np.interp(bt / fs, t[np.isfinite(y)], y[np.isfinite(y)])
                dots.set_data(bt / fs, yi)
            else:
                dots.set_data([], [])
        hr = f"{60 * fs / np.median(pt.rr):.0f} bpm" if pt.rr else "--"
        dup = n_samples - len(seen)
        missing = (last_idx - first_idx + 1 - len(seen)) if first_idx is not None else 0
        title.set_text(f"HR {hr} (display only)   |   {time.time() - t0:5.0f}/{args.seconds:.0f} s"
                       f"   missing {missing}  dup {dup}  malformed {n_bad}")
        if not reader.is_alive():
            plt.close(fig)
        return line, dots, title

    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    plt.tight_layout()
    plt.show()           # blocks until the window closes
    stop.set()

reader = threading.Thread(target=record, daemon=True)
try:
    reader.start()
    if args.live:
        live_plot(reader)
    while reader.is_alive():
        reader.join(0.2)
except KeyboardInterrupt:
    print("\ninterrupted")
    stop.set()
    reader.join(2)
finally:
    ser.close()

elapsed = time.time() - t0
print(f"\n--- {out} ---")
print(f"  wall time      : {elapsed:.1f} s")
print(f"  samples written: {n_samples}")
print(f"  malformed lines: {n_bad} (rejected, not written)")
if first_idx is not None:
    span = last_idx - first_idx + 1
    missing = span - len(seen)
    print(f"  index span     : {first_idx}..{last_idx} ({span})")
    # A gap in the monotonic index means the firmware produced a sample that
    # never reached this file - dropped by USB-CDC backpressure, not by the
    # sensor. It corrupts exactly one RR interval, so it has to be counted.
    print(f"  index gaps     : {missing} ({100*missing/span:.3f}% of span)")
    # Repeated indices are lines the host serial path delivered more than once
    # (seen on WSL/usbip). They are kept in the CSV as received; counted here
    # separately so they cannot cancel out missing samples in the figure above.
    print(f"  duplicates     : {n_samples - len(seen)}")
    # Rate from the device's own clock, not wall time: the wall-clock figure is
    # skewed by however long the port took to open relative to t0, which made an
    # otherwise-clean 256 SPS look like 248 or 267 depending on the run.
    if first_us is not None and last_us > first_us:
        dev_span_s = (last_us - first_us) / 1e6
        print(f"  device rate    : {(span - 1)/dev_span_s:.2f} SPS (expected {args.sps})")
    print(f"  wall-clock rate: {n_samples/elapsed:.2f} SPS (includes port-open latency)")
