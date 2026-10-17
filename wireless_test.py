#!/usr/bin/env python3
"""Soak-test WiFi (and log BLE) on the custom ESP32-C3 board running wireless_test.ino.

    ./wireless_test.py --minutes 60 --label soak_both

The laptop must be on the same network as the board (the phone hotspot).
Connections go OUT from here to the board: WSL2 sits behind NAT and cannot
accept inbound connections from the LAN, but outbound ones work.

Measures, for the whole run:
  - UDP echo (port 5005): loss, round-trip latency, longest outage
  - TCP stream (port 5006): throughput, in short bursts every few minutes
  - serial log: reboots, brownouts, WiFi disconnects, BLE counters, heap
BLE packet loss is measured on the phone (the ECG app shows it); the board's
side of it (connections, disconnects, notify failures) is in the serial log.

Writes captures/<stamp>_wtest_<label>.log (every serial line, host-timestamped),
..._udp.csv (one row per UDP packet) and ..._summary.txt.
"""
import argparse, csv, datetime, pathlib, re, socket, statistics, struct, sys, threading, time
import serial

ap = argparse.ArgumentParser()
ap.add_argument("--serial", default="/dev/ttyUSB0")
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--ip", help="board IP; read from the serial status line if omitted")
ap.add_argument("--minutes", type=float, default=60.0)
ap.add_argument("--label", default="soak")
ap.add_argument("--udp-rate", type=float, default=20.0, help="UDP echo packets per second")
ap.add_argument("--udp-payload", type=int, default=64)
ap.add_argument("--tcp-every", type=float, default=300.0, help="seconds between TCP bursts")
ap.add_argument("--tcp-seconds", type=float, default=10.0)
args = ap.parse_args()

# Proposed pass criteria. These are OUR proposal, not a standard - if whoever
# assigned the test has numbers, put them here. For scale: the ECG stream needs
# 256 SPS x 3 bytes = 6 kbit/s, so any working link has huge headroom on rate;
# what matters is that it stays up.
CRIT_UDP_LOSS_PCT      = 1.0    # %
CRIT_UDP_OUTAGE_S      = 5.0    # longest run of consecutive lost packets
CRIT_WIFI_OUTAGE_S     = 10.0   # longest disconnect before auto-reconnect
CRIT_TCP_MIN_MBPS      = 1.0    # every burst must connect and exceed this
CRIT_HEAP_DROP_PCT     = 10.0   # free-heap drop start -> end (leak check)

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
out = pathlib.Path("captures") / f"{stamp}_wtest_{args.label}"
out.parent.mkdir(exist_ok=True)
stop = threading.Event()
lock = threading.Lock()

# ------------------------------------------------------------------ serial
status_lines, boot_lines, event_lines = [], [], []
board_ip = [args.ip]
serial_error = []   # set if the reader dies - a silent dead logger would fake a clean run
KV = re.compile(r"(\w+)=(\S+)")

def serial_reader():
    try:
        _serial_reader()
    except Exception as e:
        serial_error.append(repr(e))
        print(f"!! serial logging stopped: {e!r}")

def _serial_reader():
    ser = serial.Serial(args.serial, args.baud, timeout=0.5)
    try:
        ser.dtr = False; ser.rts = False      # this board doesn't wire them to EN/BOOT, but don't toggle anyway
    except OSError:
        pass                                  # ports without modem lines (e.g. a pty)
    ser.reset_input_buffer()
    ser.write(b"s")                            # ask for a status line now
    with open(out.with_suffix(".log"), "w") as log:
        while not stop.is_set():
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").rstrip()
            now = time.time()
            log.write(f"{now:.3f} {line}\n"); log.flush()
            if line.startswith("# st "):
                kv = dict(KV.findall(line))
                with lock:
                    status_lines.append((now, kv))
                if kv.get("ip", "-") != "-" and not board_ip[0]:
                    board_ip[0] = kv["ip"]
            elif line.startswith("# boot "):
                # The WSL/usbip serial path has been seen to deliver the same
                # line several times, so count distinct boot numbers, not lines.
                m = re.search(r"# boot n=(\d+)", line)
                with lock:
                    if m and m.group(1) not in {n for _, n in boot_lines}:
                        boot_lines.append((now, m.group(1)))
                        print(f"!! board booted during test: {line}")
            elif line.startswith("# wifi") or line.startswith("# ble"):
                with lock:
                    event_lines.append((now, line))
                print(f"   {line}")
                m = re.search(r"# wifi up ip=(\S+)", line)
                if m:
                    board_ip[0] = m.group(1)
    ser.close()

# ------------------------------------------------------------------ UDP echo
sent = {}      # seq -> send time
rtt = {}       # seq -> round trip seconds

def udp_run(ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    pad = b"\x00" * max(0, args.udp_payload - 12)

    def rx():
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(data) >= 12:
                seq, t_ns = struct.unpack_from("<IQ", data)
                with lock:
                    if seq in sent and seq not in rtt:
                        rtt[seq] = (time.monotonic_ns() - t_ns) / 1e9

    threading.Thread(target=rx, daemon=True).start()
    period = 1.0 / args.udp_rate
    seq, t_next = 0, time.monotonic()
    while not stop.is_set():
        with lock:
            sent[seq] = time.time()
        try:
            sock.sendto(struct.pack("<IQ", seq, time.monotonic_ns()) + pad, (ip, 5005))
        except OSError:
            pass                                  # counted as lost: no echo will come
        seq += 1
        t_next += period
        time.sleep(max(0.0, t_next - time.monotonic()))
    time.sleep(2.0)                               # let late echoes land
    sock.close()

# ------------------------------------------------------------------ TCP bursts
tcp_results = []   # (time, mbps or None, note)

def tcp_burst(ip):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 5006), timeout=5)
        s.settimeout(2)
        n, start = 0, time.monotonic()
        while time.monotonic() - start < args.tcp_seconds:
            chunk = s.recv(65536)
            if not chunk:
                break
            n += len(chunk)
        dt = time.monotonic() - start
        s.close()
        mbps = n * 8 / dt / 1e6 if dt > 0 else 0.0
        tcp_results.append((t0, mbps, f"{n} bytes in {dt:.1f}s"))
        print(f"   tcp burst: {mbps:.2f} Mbit/s")
    except OSError as e:
        tcp_results.append((t0, None, str(e)))
        print(f"   tcp burst FAILED: {e}")

# ------------------------------------------------------------------ run
threading.Thread(target=serial_reader, daemon=True).start()
print(f"logging serial from {args.serial}; waiting for board IP ...")
t_wait = time.time()
while not board_ip[0] and time.time() - t_wait < 60 and not serial_error:
    time.sleep(0.5)
if not board_ip[0]:
    stop.set()
    sys.exit("no IP from the board within 60 s - is it on the hotspot? (check the .log)")
ip = board_ip[0]
print(f"board at {ip}; running {args.minutes:g} min, UDP {args.udp_rate:g}/s, "
      f"TCP {args.tcp_seconds:g}s every {args.tcp_every:g}s")

t_start = time.time()
udp_thread = threading.Thread(target=udp_run, args=(ip,), daemon=True)
udp_thread.start()
next_tcp = time.time() + 5
try:
    while time.time() - t_start < args.minutes * 60:
        if time.time() >= next_tcp:
            tcp_burst(ip)
            next_tcp = time.time() + args.tcp_every
        time.sleep(0.5)
        el = time.time() - t_start
        if int(el) % 60 == 0 and el > 1:
            with lock:
                n_s, n_r = len(sent), len(rtt)
            print(f"   {el/60:.0f} min: udp {n_r}/{n_s} echoed")
            time.sleep(1)
except KeyboardInterrupt:
    print("interrupted - summarising what was collected")
stop.set()
udp_thread.join(timeout=5)
duration = time.time() - t_start

# ------------------------------------------------------------------ summary
with lock:
    seqs = sorted(sent)
    got = dict(rtt)
lost_flags = [s not in got for s in seqs]
n_sent, n_got = len(seqs), len(got)
loss_pct = 100.0 * (n_sent - n_got) / n_sent if n_sent else 100.0
longest_run = run = 0
for lost in lost_flags:
    run = run + 1 if lost else 0
    longest_run = max(longest_run, run)
udp_outage_s = longest_run / args.udp_rate
r_ms = sorted(v * 1000 for v in got.values())
def pct(p): return r_ms[min(len(r_ms) - 1, int(p / 100 * len(r_ms)))] if r_ms else float("nan")

with open(str(out) + "_udp.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["seq", "sent_unix", "rtt_ms"])
    for s in seqs:
        w.writerow([s, f"{sent[s]:.3f}", f"{got[s]*1000:.2f}" if s in got else ""])

first = status_lines[0][1] if status_lines else {}
last = status_lines[-1][1] if status_lines else {}
def iv(d, k):
    try: return int(d.get(k, 0))
    except ValueError: return 0
wifi_disc = iv(last, "disc") - iv(first, "disc")
ble_disc = iv(last, "ble_disc") - iv(first, "ble_disc")
ble_pkts = iv(last, "ble_pkts") - iv(first, "ble_pkts")
ble_fail = iv(last, "ble_fail") - iv(first, "ble_fail")
wifi_outage_s = iv(last, "longest_outage_ms") / 1000
rssis = [iv(kv, "rssi") for _, kv in status_lines if iv(kv, "wifi") == 1]
heap0, heap1 = iv(first, "heap"), iv(last, "heap")
heap_drop = 100.0 * (heap0 - heap1) / heap0 if heap0 else 0.0
tcp_ok = [m for _, m, _ in tcp_results if m is not None]
tcp_fail = sum(1 for _, m, _ in tcp_results if m is None)

checks = [
    # A reader stuck inside open() raises nothing, so "no error" is not proof it
    # worked: require status lines covering the run (one every 5 s from the board).
    ("serial log ran for the whole test",
     not serial_error and len(status_lines) >= max(1, int(duration / 5 * 0.8)),
     serial_error[0] if serial_error else f"{len(status_lines)} status lines (expected ~{int(duration/5)})"),
    ("no reboots during test",          len(boot_lines) == 0, f"{len(boot_lines)} distinct boot(s)"),
    ("no brownouts (board counter)",    iv(last, "brownouts") == iv(first, "brownouts"),
                                        f"brownouts {iv(first,'brownouts')} -> {iv(last,'brownouts')} (lifetime)"),
    (f"UDP loss < {CRIT_UDP_LOSS_PCT}%", loss_pct < CRIT_UDP_LOSS_PCT, f"{loss_pct:.2f}% ({n_sent-n_got}/{n_sent})"),
    (f"UDP outage < {CRIT_UDP_OUTAGE_S}s", udp_outage_s < CRIT_UDP_OUTAGE_S, f"longest {udp_outage_s:.1f}s"),
    (f"WiFi outage < {CRIT_WIFI_OUTAGE_S}s", wifi_outage_s < CRIT_WIFI_OUTAGE_S,
                                        f"{wifi_disc} disconnect(s), longest {wifi_outage_s:.1f}s"),
    (f"TCP bursts all > {CRIT_TCP_MIN_MBPS} Mbit/s", tcp_fail == 0 and bool(tcp_ok) and min(tcp_ok) > CRIT_TCP_MIN_MBPS,
                                        f"{len(tcp_ok)} ok, {tcp_fail} failed" +
                                        (f", min {min(tcp_ok):.2f} / median {statistics.median(tcp_ok):.2f} Mbit/s" if tcp_ok else "")),
    ("BLE: no disconnects, no notify failures", ble_disc == 0 and ble_fail == 0,
                                        f"disc {ble_disc}, notify fail {ble_fail}, sent {ble_pkts} pkts "
                                        f"(phone-side loss: read it off the app)"),
    (f"heap drop < {CRIT_HEAP_DROP_PCT}%", heap_drop < CRIT_HEAP_DROP_PCT, f"{heap0} -> {heap1} B ({heap_drop:.1f}%)"),
]

lines = [
    f"wireless soak test  {stamp}  label={args.label}",
    f"board {ip}  duration {duration/60:.1f} min  ble_on={last.get('ble_on','?')} wifi_on={last.get('wifi_on','?')}",
    f"UDP  sent {n_sent}  echoed {n_got}  RTT ms p50 {pct(50):.0f}  p95 {pct(95):.0f}  p99 {pct(99):.0f}  max {pct(100):.0f}",
    f"RSSI dBm  min {min(rssis) if rssis else 'n/a'}  median {statistics.median(rssis) if rssis else 'n/a'}  max {max(rssis) if rssis else 'n/a'}",
    "",
    "checks (proposed criteria - see top of wireless_test.py):",
]
for name, ok, detail in checks:
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name:38s} {detail}")
lines.append("")
lines.append(f"OVERALL: {'PASS' if all(ok for _, ok, _ in checks) else 'FAIL'}")
text = "\n".join(lines)
print("\n" + text)
open(str(out) + "_summary.txt", "w").write(text + "\n")
print(f"\nfiles: {out}.log, {out}_udp.csv, {out}_summary.txt")
