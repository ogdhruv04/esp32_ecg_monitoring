"""Synthetic firmware output, for testing the host tools without a board.

NOT A RECORDING. Nothing this produces may be saved under captures/ or quoted
as a result; its boot line says "device: SIM" so a log made from it is
recognisable. It imitates what sketch.ino sends on the reference board: S lines
in drains of 4, then that drain's sensor lines (M every 4 ECG samples, P from a
free-running PPG clock, G every 16, T every 256) and the '#' lines every 5 s.

    from sim_stream import lines
    for ln in lines(seconds=30, drop={("M", 100)}): ...

Faults, so the checks can be shown to catch them:
    drop        set of (prefix, counter): lines lost on the link
    repeat      set of (prefix, counter): lines delivered twice
    torn        set of (prefix, counter): lines cut short
    late_drain  set of drain numbers that are skipped, so the next drain holds
                8 ECG samples and one IMU reading is taken late
Events, for sensor_check.py:
    taps        seconds at which the IMU sees a short spike
    breath      second at which the GSR output starts a 60 mV dip
"""
import math

ECG_SPS = 256


def lines(seconds=30.0, ppg_sps=100.0, base_us=5_000_000, drop=(), repeat=(), torn=(),
          late_drain=(), sensors=True, taps=(), breath=None):
    drop, repeat, torn, late_drain = set(drop), set(repeat), set(torn), set(late_drain)
    out = []

    def emit(prefix, counter, text):
        key = (prefix, counter)
        if key in drop:
            return
        if key in torn:
            text = text[: len(text) // 2]
        out.append(text)
        if key in repeat:
            out.append(text)

    u32 = lambda t: int(t) % 2**32
    out.append("# device: SIM  (synthetic stream from sim_stream.py, not a recording)")
    out.append("# fmt: S,index,isr_micros,value,etag,leadoff")
    if sensors:
        out.append("# sens ppg: addr:57 part:15 rev:03 fifo:00 mode:03 spo2:27 pa:1F/1F sps:100 ok")
    n_total = int(seconds * ECG_SPS)
    idx = 0                     # ECG samples produced
    drained = 0                 # ECG samples drained
    imu_n = gsr_n = temp_n = ppg_n = 0
    imu_slot = gsr_slot = temp_slot = 0
    drain_no = 0
    next_stats = 5 * ECG_SPS
    hr_hz = 1.2
    while idx < n_total:
        idx += 4
        drain_no += 1
        if drain_no in late_drain:
            continue                                    # this interrupt was not serviced
        t_isr = base_us + idx * 1e6 / ECG_SPS
        for k in range(drained + 1, idx + 1):
            ph = (k / ECG_SPS * hr_hz) % 1.0
            val = int(2000 * math.exp(-((ph - 0.5) / 0.012) ** 2) + 40 * math.sin(k / 9.0))
            emit("S", k, f"S,{k},{u32(t_isr)},{val},{2 if k == idx else 0},0")
        drained = idx
        if not sensors:
            continue
        if idx // 4 != imu_slot:
            imu_slot = idx // 4
            imu_n += 1
            ts = idx / ECG_SPS
            az = 16300 + (9000 if any(0 <= ts - tap < 0.03 for tap in taps) else 0) + (imu_n * 7) % 11
            emit("M", imu_n, f"M,{imu_n},{idx},{u32(t_isr + 700)},{120},{-80},{az},{3},{-2},{1}")
        t_poll = t_isr + 1500
        while base_us + (ppg_n + 1) * 1e6 / ppg_sps <= t_poll:
            ppg_n += 1
            tp = ppg_n / ppg_sps
            pulse = math.sin(2 * math.pi * hr_hz * (tp - 0.2))
            emit("P", ppg_n, f"P,{ppg_n},{idx},{u32(t_poll)},{90000 + int(900 * pulse)},"
                             f"{110000 + int(1500 * pulse)}")
        if idx // 16 != gsr_slot:
            gsr_slot = idx // 16
            gsr_n += 1
            ts = idx / ECG_SPS
            mv = 900 + 2 * math.sin(ts / 7.0) + (gsr_n * 5) % 3
            if breath is not None and ts > breath + 1.5:
                mv -= 60 * (1 - math.exp(-(ts - breath - 1.5) / 1.5)) * math.exp(-(ts - breath - 1.5) / 8)
            emit("G", gsr_n, f"G,{gsr_n},{idx},{u32(t_isr + 2100)},{int(mv * 8 * 4095 / 3100)},{int(mv * 8)}")
        if idx // 256 != temp_slot:
            temp_slot = idx // 256
            temp_n += 1
            emit("T", temp_n, f"T,{temp_n},{idx},{u32(t_isr + 2700)},{int(33.5 / 0.00390625) + temp_n % 3}")
        if idx >= next_stats:
            next_stats += 5 * ECG_SPS
            out.append("# 5s: valid:1280 ovf:0 empty:0 other:0 rate:256.00 | life: ...")
            out.append("# cfg emux:0B0000 cal:720000 mode:begin")
            out.append(f"# sens: i2c:400k ppg:1 n:{ppg_n} fifo_lost:0 err:0 pa:1F part:15 "
                       f"| imu:1@68 n:{imu_n} err:0 whoami:68 | temp:1 n:{temp_n} err:0 "
                       f"| gsr:1 n:{gsr_n} | logdrop:0")
    return out
