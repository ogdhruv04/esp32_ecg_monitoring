"""The firmware's extra-sensor lines (P, M, T, G): parsing and saving.

Shared by capture.py and capture_dual.py so both write the same files, and by
integrity.py so it checks what they wrote. The line formats are defined in
sketch.ino ("Extra sensors") and must match it.

Each stream goes to its own CSV next to the ECG file, created when the first
line of that kind arrives:

    captures/<stamp>_<label>.csv         ECG, unchanged
    captures/<stamp>_<label>_ppg.csv     ppg_index,ecg_index,micros,red,ir
    captures/<stamp>_<label>_imu.csv     seq,ecg_index,micros,ax,ay,az,gx,gy,gz
    captures/<stamp>_<label>_temp.csv    seq,ecg_index,micros,raw
    captures/<stamp>_<label>_gsr.csv     seq,ecg_index,micros,adc_sum,mv_sum

A board with no sensors (the ring) sends none of these lines and gets no
sidecar files. Rows are written as received: nothing is repaired or reordered
here, so the files can be judged by integrity.py.
"""
import pathlib

ECG_SPS = 256

# line prefix -> (file suffix, columns). The first column is the stream's own
# counter: every reading the firmware takes gets the next number, so a hole in
# it on the host is a line that was lost on the way.
STREAMS = {
    "P": ("ppg",  ["ppg_index", "ecg_index", "micros", "red", "ir"]),
    "M": ("imu",  ["seq", "ecg_index", "micros", "ax", "ay", "az", "gx", "gy", "gz"]),
    "T": ("temp", ["seq", "ecg_index", "micros", "raw"]),
    "G": ("gsr",  ["seq", "ecg_index", "micros", "adc_sum", "mv_sum"]),
}

# How the firmware schedules each stream (sketch.ino: IMU_EVERY, GSR_EVERY,
# TEMP_EVERY, PPG_SPS, GSR_OVERSAMPLE). ECG samples per reading for the streams
# sampled on the ECG clock; the MAX30102 runs on its own clock instead.
EVERY = {"imu": 4, "gsr": 16, "temp": 256}
PPG_SPS = 100
GSR_OVERSAMPLE = 8

# Scale factors, from docs/sensor_datasheet_check.md.
ACCEL_LSB_PER_G = 16384.0        # MPU6050, +-2 g
GYRO_LSB_PER_DPS = 131.0         # MPU6050, +-250 deg/s
TEMP_C_PER_LSB = 0.00390625      # MAX30205
PPG_FULL_SCALE = 262143          # MAX30102, 18-bit


class LineReader:
    """readline() for a pyserial port, taking everything that has arrived in
    one read instead of one byte per call.

    pyserial's own readline() does a select() and a read() for every byte,
    which caps how fast one thread can take data in, and the sensor lines
    roughly double what the reference board sends. Both readers are measured
    on a pseudo-terminal by ./test_capture_sensors.py --bench; the result is
    analysis/host_reader_benchmark.txt. A pty is not the WSL/usbip serial
    path, so that file compares the two readers and is not a capacity figure
    for the real link. This returns b"" on a timeout like pyserial does, but
    keeps a half-received line for the next call instead of handing it over
    torn.
    """

    def __init__(self, ser):
        self.ser = ser
        self.buf = bytearray()

    def readline(self):
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line = bytes(self.buf[: i + 1])
                del self.buf[: i + 1]
                return line
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if not chunk:
                return b""
            self.buf += chunk


def sidecar(ecg_csv, name):
    """Path of one sensor stream's CSV for a given ECG CSV."""
    p = pathlib.Path(ecg_csv)
    return p.with_name(f"{p.stem}_{name}.csv")


class SensorWriter:
    """Routes sensor lines into their CSVs and keeps running counts.

        sens = SensorWriter(ecg_csv_path, host_time=True)
        if sens.handle(line, time.time()): ...   # True: it was a sensor line
        sens.close(); print("\n".join(sens.summary()))
    """

    def __init__(self, ecg_csv, host_time=False):
        self.ecg_csv = pathlib.Path(ecg_csv)
        self.host_time = host_time
        self.files = {}
        self.stats = {name: {"rows": 0, "bad": 0, "missing": 0, "repeats": 0,
                             "first": None, "last": None}
                      for name, _ in STREAMS.values()}

    def handle(self, line, t=None):
        if len(line) < 2 or line[1] != "," or line[0] not in STREAMS:
            return False
        name, cols = STREAMS[line[0]]
        st = self.stats[name]
        parts = line[2:].split(",")
        # Parse before writing, as for ECG rows: the serial path has delivered
        # torn lines, and one must not end up in a file as a short row.
        try:
            if len(parts) != len(cols):
                raise ValueError
            seq = int(parts[0])
            for p in parts[1:]:
                int(p)
        except ValueError:
            st["bad"] += 1
            return True
        f = self.files.get(name)
        if f is None:
            f = self.files[name] = sidecar(self.ecg_csv, name).open("w")
            f.write(("host_time," if self.host_time else "") + ",".join(cols) + "\n")
        f.write((f"{t:.6f}," if self.host_time else "") + ",".join(parts) + "\n")
        st["rows"] += 1
        if st["first"] is None:
            st["first"] = seq
        elif seq > st["last"] + 1:
            st["missing"] += seq - st["last"] - 1
        elif seq <= st["last"]:
            st["repeats"] += 1
        if st["last"] is None or seq > st["last"]:
            st["last"] = seq
        return True

    def close(self):
        for f in self.files.values():
            f.close()

    def summary(self):
        """One line per stream that produced anything. A running count only:
        integrity.py is the check."""
        out = []
        for name, _ in STREAMS.values():
            st = self.stats[name]
            if not st["rows"] and not st["bad"]:
                continue
            span = f"{st['first']}..{st['last']}" if st["rows"] else "-"
            out.append(f"{name:4}: {st['rows']:6d} rows, counter {span}, missing {st['missing']}, "
                       f"repeated {st['repeats']}, malformed {st['bad']}"
                       + (f" -> {sidecar(self.ecg_csv, name).name}" if st["rows"] else ""))
        return out
