#!/usr/bin/env python3
"""End-to-end test of capture.py, capture_dual.py and integrity.py on the
extra-sensor streams, using a synthetic firmware stream (sim_stream.py) in
place of the serial port. No board needed; nothing is written to captures/.

    ./test_capture_sensors.py        (or: pytest test_capture_sensors.py)
    ./test_capture_sensors.py --bench    reader speed -> analysis/host_reader_benchmark.txt

Each test injects known faults and requires integrity.py to report exactly
those, so the check is shown to catch them rather than assumed to.
"""
import os, pathlib, re, runpy, subprocess, sys, tempfile, time
import serial
import sim_stream

REPO = pathlib.Path(__file__).resolve().parent


class FakeSerial:
    """Stands in for serial.Serial: hands out prepared lines, then nothing."""
    streams = {}

    def __init__(self, port, baud, timeout=1):
        self.it = iter(self.streams[port])
        self.dtr = self.rts = False

    def reset_input_buffer(self):
        pass

    in_waiting = 0

    def read(self, n):
        # several lines per read, cut at arbitrary places, as a real port does
        chunk = b""
        try:
            for _ in range(7):
                chunk += (next(self.it) + "\n").encode()
        except StopIteration:
            if not chunk:
                time.sleep(0.01)
                return self.tail()
        cut = len(chunk) - 11 if len(chunk) > 11 else len(chunk)
        out, self.held = self.held + chunk[:cut], chunk[cut:]
        return out

    held = b""

    def tail(self):
        out, self.held = self.held, b""
        return out

    def close(self):
        pass


def run_tool(script, argv, streams):
    """Run a capture script in the current directory with the fake port."""
    FakeSerial.streams = streams
    real, old_argv = serial.Serial, sys.argv
    serial.Serial = FakeSerial
    sys.argv = [script] + argv
    sys.path.insert(0, str(REPO))
    try:
        runpy.run_path(str(REPO / script), run_name="__main__")
    finally:
        serial.Serial, sys.argv = real, old_argv
        sys.path.remove(str(REPO))


def integrity(*csvs):
    pathlib.Path("analysis").mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, str(REPO / "integrity.py"), *map(str, csvs)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def section(report, filename):
    """The lines of an integrity report that belong to one file."""
    out, on = [], False
    for ln in report.splitlines():
        if ln.strip().endswith(".csv"):
            on = ln.strip() == filename
        elif on:
            out.append(ln)
    return "\n".join(out)


def in_tmp(fn):
    def wrapper():
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                fn()
            finally:
                os.chdir(cwd)
    wrapper.__name__ = fn.__name__
    return wrapper


@in_tmp
def test_clean_stream_single_capture():
    # micros wraps past 2^32 three seconds in, as it will on a board that has
    # been up for 71 minutes; the lag check must not see that as a jump
    run_tool("capture.py", ["--port", "X", "--seconds", "2", "--label", "clean"],
             {"X": sim_stream.lines(30, ppg_sps=100.4, base_us=2**32 - 3_000_000)})
    ecg = next(pathlib.Path("captures").glob("*_clean.csv"))
    names = sorted(p.name[len(ecg.stem):] for p in pathlib.Path("captures").glob("*_clean_*.csv"))
    assert names == ["_gsr.csv", "_imu.csv", "_ppg.csv", "_temp.csv"], names
    rep = integrity(ecg)
    assert "missing 0  gaps 0  duplicates 0  backward jumps 0" in rep.split(ecg.name)[1].split("\n")[2]
    for name, rows in (("ppg", 3012), ("imu", 1920), ("temp", 30), ("gsr", 480)):
        sec = section(rep, f"{ecg.stem}_{name}.csv")
        assert f"rows {rows}  malformed 0" in sec, (name, sec)
        assert "missing 0  gaps 0  repeated 0  backward jumps 0" in sec, (name, sec)
        assert "backward 0  outside the ECG file's range 0" in sec, (name, sec)
        assert "negative 0" in sec and "not in the ECG file: 0" in sec, (name, sec)
    assert "4 (scheduled) on 100.00%" in section(rep, f"{ecg.stem}_imu.csv")
    # the PPG clock was set 0.4% fast; the rate against the ECG clock must show it
    rate = float(re.search(r"rate ([\d.]+) per second", section(rep, f"{ecg.stem}_ppg.csv")).group(1))
    assert abs(rate - 100.4) < 0.1, rate
    assert "median 0.70 ms" in section(rep, f"{ecg.stem}_imu.csv")
    assert "firmware's last counter line" in rep and "logdrop:0" in rep


@in_tmp
def test_faults_are_reported():
    faults = dict(drop={("M", 100), ("M", 101), ("M", 500), ("P", 250), ("G", 7), ("S", 1000)},
                  repeat={("P", 900), ("T", 5)}, torn={("M", 800), ("G", 40)}, late_drain={300})
    run_tool("capture.py", ["--port", "X", "--seconds", "2", "--label", "faulty"],
             {"X": sim_stream.lines(30, **faults)})
    ecg = next(pathlib.Path("captures").glob("*_faulty.csv"))
    rep = integrity(ecg)
    imu, ppg = section(rep, f"{ecg.stem}_imu.csv"), section(rep, f"{ecg.stem}_ppg.csv")
    gsr, temp = section(rep, f"{ecg.stem}_gsr.csv"), section(rep, f"{ecg.stem}_temp.csv")
    # 3 dropped + 1 torn (rejected by capture, so absent from the file); drain 300
    # was skipped, so one reading was never taken: that is a skipped slot, not a hole
    assert "missing 4  gaps 3  repeated 0" in imu, imu
    assert "skipped readings (step >= 8) 1" in imu and "largest 8" in imu, imu
    assert "missing 1  gaps 1  repeated 1" in ppg, ppg
    assert "missing 2  gaps 2  repeated 0" in gsr, gsr
    assert "missing 0  gaps 0  repeated 1" in temp, temp
    # ECG line 1000 was lost: readings stamped with it cannot be checked, and say so
    assert "not in the ECG file: 1" in imu, imu
    assert "missing 1  gaps 1" in rep.split(ecg.name)[1], rep


@in_tmp
def test_dual_capture_ring_has_no_sensors():
    run_tool("capture_dual.py", ["--ring", "R", "--ref", "F", "--seconds", "2", "--label", "dual"],
             {"R": sim_stream.lines(20, sensors=False), "F": sim_stream.lines(20, drop={("G", 3)})})
    cap = pathlib.Path("captures")
    ring, ref = next(cap.glob("*_dual_ring.csv")), next(cap.glob("*_dual_ref.csv"))
    assert not list(cap.glob("*_dual_ring_*.csv")), "the ring sent no sensor lines"
    assert len(list(cap.glob("*_dual_ref_*.csv"))) == 4
    assert ref.with_suffix(".log").read_text().count("# sens: i2c:") == 4
    head = (cap / f"{ref.stem}_imu.csv").read_text().splitlines()[0]
    assert head == "host_time,seq,ecg_index,micros,ax,ay,az,gx,gy,gz", head
    rep = integrity(ring, ref)
    assert "missing 1  gaps 1" in section(rep, f"{ref.stem}_gsr.csv")
    assert "missing 0  gaps 0  repeated 0" in section(rep, f"{ref.stem}_imu.csv")
    assert f"{ring.stem}_" not in rep                 # no sensor sections for the ring
    assert list(pathlib.Path("analysis").glob("integrity_*_dual.txt"))
    # sensor_check has to read the dual-capture layout too (extra host_time column)
    r = subprocess.run([sys.executable, str(REPO / "sensor_check.py"), str(ref), "--checks", "temp,imu"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Temperature" in r.stdout and "PASS: sd <=" in r.stdout, r.stdout
    assert "PPG" not in r.stdout and "GSR" not in r.stdout, r.stdout


@in_tmp
def test_sensor_check_finds_the_events():
    run_tool("capture.py", ["--port", "X", "--seconds", "3", "--label", "events"],
             {"X": sim_stream.lines(60, ppg_sps=100.3, taps=(10, 12, 14, 16.5, 19), breath=30)})
    ecg = next(pathlib.Path("captures").glob("*_events.csv"))
    r = subprocess.run([sys.executable, str(REPO / "sensor_check.py"), str(ecg),
                        "--taps", "5", "--breath", "30"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rep = r.stdout
    assert "PASS: 5 spikes for 5 taps made" in rep, rep
    assert "at 10.0, 12.0, 14.0, 16.5, 19.0 s" in rep, rep
    assert re.search(r"against the ECG clock: 100\.[23]\d\d per second", rep), rep
    assert re.search(r"difference [+-]0\.\d+ bpm\n  PASS", rep), rep       # both made at 72 bpm
    assert re.search(r"largest move in the 15 s after: -\d\d\.\d mV", rep), rep
    assert rep.count("PASS") == 4 and "FAIL" not in rep, rep
    # and the same capture with the wrong tap count must fail that check
    r = subprocess.run([sys.executable, str(REPO / "sensor_check.py"), str(ecg), "--taps", "4"],
                       capture_output=True, text=True)
    assert "FAIL: 5 spikes for 4 taps made" in r.stdout, r.stdout


def bench(seconds=10.0):
    """Lines per second each reader can take from a raw pseudo-terminal that is
    written as fast as it will accept. Compares pyserial's readline() with
    sensor_streams.LineReader; saved, because sensor_streams.py cites it."""
    import datetime, pty, threading, tty
    from sensor_streams import LineReader
    line = b"M,12345,123456,1234567890,-12345,-12345,-12345,-123,-123,-123\n"
    rows = []
    for label, wrap in (("pyserial readline()", lambda s: s), ("LineReader", LineReader)):
        m, s = pty.openpty()
        tty.setraw(m); tty.setraw(s)
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                os.write(m, line)
        threading.Thread(target=writer, daemon=True).start()
        ser = serial.Serial(os.ttyname(s), 460800, timeout=1)
        r = wrap(ser)
        t0 = time.time(); n = torn = 0
        while time.time() - t0 < seconds:
            ln = r.readline()
            if ln:
                n += 1
                torn += ln != line
        dt = time.time() - t0
        stop.set()
        rows.append(f"  {label:20}: {n/dt:8.0f} lines/s  {n*len(line)/dt/1000:7.1f} kB/s  "
                    f"({n} lines in {dt:.1f} s, {torn} not intact)")
    text = (f"# ./test_capture_sensors.py --bench   {datetime.datetime.now():%Y-%m-%d %H:%M}\n"
            f"# One reader thread taking {len(line)}-byte lines from a raw pty that another thread\n"
            f"# writes as fast as it is accepted. A pty is not the WSL/usbip serial path: this\n"
            f"# compares the two readers, it is not a capacity figure for the real link.\n"
            + "\n".join(rows) + "\n")
    out = REPO / "analysis" / "host_reader_benchmark.txt"
    out.write_text(text)
    print(text + f"saved {out}")


if __name__ == "__main__":
    if "--bench" in sys.argv:
        bench()
        sys.exit(0)
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
