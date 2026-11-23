# Extra-sensor claims checked against the datasheets

Companion to `docs/MAX30003_datasheet_check.md`, for the three I2C sensors on the reference
board. Every register value and scale factor that `sketch.ino`, `sensor_streams.py` and
`sensor_check.py` use is listed here with the page it comes from. Checked 10 Nov 2026.

The datasheet PDFs are **not in the repo** (only the schematic was cleared for commit). Sources:

| Part | Document | Got from |
|---|---|---|
| MAX30102 | Maxim 19-7740, **Rev 1, 10/18**, 32 pages | web.archive.org copy of `datasheets.maximintegrated.com/en/ds/MAX30102.pdf` (analog.com timed out) |
| MAX30205 | Maxim 19-8505, **Rev 0, 3/16**, 15 pages | web.archive.org copy of `datasheets.maximintegrated.com/en/ds/MAX30205.pdf` |
| MPU6050 | InvenSense register map RM-MPU-6000A-00, **Rev 4.0** ("RM"), 47 pages | `cdn.sparkfun.com/datasheets/Sensors/Accelerometers/RM-MPU-6000A.pdf` |
| MPU6050 | InvenSense product specification PS-MPU-6000A-00, **Rev 3.4, 08/19/2013** ("PS"), 52 pages | `cdiweb.com/datasheets/invensense/mpu-6050_datasheet_v3 4.pdf` |

Printed page numbers match PDF page numbers in all four.

Verdicts: ✅ confirmed · ⚠️ the datasheet leaves it open, or raises something that needs a hardware check

## MAX30102 (PPG)

| # | Claim | Datasheet | Verdict |
|---|---|---|---|
| 1 | I2C address is fixed at 0x57 (write 0xAE, read 0xAF) | p.5; p.29 Table 17 | ✅ |
| 2 | `PART_ID` (0xFF) reads 0x15; `REV_ID` is 0xFE | p.11 | ✅ The firmware refuses the part if 0xFF does not read 0x15. |
| 3 | FIFO registers: write pointer 0x04, overflow counter 0x05, read pointer 0x06, data 0x07; pointers are 5 bits | p.10; p.13 | ✅ |
| 4 | FIFO holds 32 samples. In SpO2 mode a sample is 6 bytes: 3 for red, then 3 for IR. LED1 is red, LED2 is IR | p.14; p.15 Figure 2; p.16 pseudo-code; p.21 Table 9 | ✅ |
| 5 | The 18 data bits are bits [17:0] of each 3-byte group; bits [23:18] are unused (mask `0x3FFFF`). Data is left-justified within those 18 bits at lower resolutions | pp.14–15 Tables 1–2 | ✅ At our 18-bit setting all 18 bits carry data. |
| 6 | Reading `FIFO_DATA` in a burst does not advance the register address, so several samples come back in one transaction | p.14 | ✅ |
| 7 | Samples waiting = write pointer − read pointer, with wrap-around | p.16 | ✅ |
| 8 | `FIFO_CONFIG` (0x08) = 0x00: `SMP_AVE` 000 = no averaging, `FIFO_ROLLOVER_EN` 0, `FIFO_A_FULL` 0 | p.17 Table 3 | ✅ |
| 9 | With rollover off, a full FIFO takes no more samples; `OVF_COUNTER` counts the lost ones, saturates at 0x1F, and resets to zero when a sample is read | p.13; p.17 | ✅ So the samples lost are the newest ones, and the firmware adds the count to `ppg_index` after emptying the FIFO. |
| 10 | When the FIFO is full the two pointers read equal (as when empty) | **Not stated.** | ⚠️ Our reading of a 32-deep FIFO with 5-bit pointers. The firmware treats "pointers equal and overflow counter non-zero" as 32 waiting, and otherwise reads whatever the pointers say, so either behaviour is handled. Only reached after a stall longer than 320 ms. |
| 11 | `MODE_CONFIG` (0x09): bit 6 `RESET` clears itself when the reset is done; `MODE` 011 = SpO2 mode, red and IR | p.18 Table 4 | ✅ |
| 12 | `SPO2_CONFIG` (0x0A) = 0x27: `SPO2_ADC_RGE` 01 = 4096 nA full scale (15.63 pA per LSB), `SPO2_SR` 001 = 100 samples/s, `LED_PW` 11 = 411 µs = 18-bit | p.18 Table 5; p.19 Tables 6–7 | ✅ 100 samples/s with 411 µs is an allowed pair (p.23 Table 11). |
| 13 | LED current registers: 0x0C red, 0x0D IR, 0.2 mA per step typical. 0x1F = 6.2 mA, 0x3F = 12.6 mA, 0x7F = 25.4 mA | p.20 Table 8 | ✅ 0x0A = 2.0 mA is interpolated, not in the table. The table's footnote: actual current "can vary widely" part to part. |
| 14 | I2C up to 400 kHz | p.5 | ✅ |
| 15 | SDA/SCL may sit on 3.3 V pull-ups while VDD is 1.8 V | p.2 abs max: VDD −0.3 to **+2.2 V**; "All Other Pins to GND" −0.3 to **+6.0 V**. p.4: VIH = 0.7 × VDD, VIL = 0.3 × VDD | ✅ for the pins. The 1.8 V **rail** is the concern: see `docs/sensor_inventory.md`, open question 3. |
| 16 | The sample clock is accurate enough to treat 100 samples/s as exact | **Not stated** anywhere in the datasheet. | ⚠️ Never assume it. `integrity.py` and `sensor_check.py` measure the MAX30102's rate against the ECG clock on every capture. |

## MAX30205 (temperature)

| # | Claim | Datasheet | Verdict |
|---|---|---|---|
| 17 | With A2 = A1 = A0 = GND the address byte is 90h, i.e. 7-bit 0x48 | p.9 Table 1 | ✅ |
| 18 | Temperature register is 0x00: 16 bits, two's complement, MSB first, 0.00390625 °C per LSB | p.10 Table 2; p.11 Table 3 | ✅ |
| 19 | Configuration register is 0x01 and powers up as 0x00: continuous conversion (D0 `SHUTDOWN` = 0), normal data format (D5 = 0) | p.10 Table 2; p.12 Tables 4–5 | ✅ The firmware writes 0x00 and reads it back. |
| 20 | A conversion takes 44 ms typical, 50 ms maximum | p.2 | ✅ We read the latest result once a second. |
| 21 | The reading is accurate to 0.1 °C | p.2: ±0.1 °C only from 37 to 39 °C; ±0.3 °C from 15 to 35.8 °C. p.4 Note 5: the limits assume a **sample period above 10 s "to eliminate self-heating effects"** | ⚠️ We convert continuously, so the stated accuracy does not apply. Treat the absolute value as uncalibrated and use the trend. A rough size for the offset: 600 µA typical supply current (p.3) at 3.3 V is 2 mW, and 41 °C/W junction-to-ambient (p.2) gives about 0.08 °C. That is an estimate from two datasheet figures, not a measurement. |
| 22 | Supply 2.7 to 3.3 V; I2C up to 400 kHz | p.2; p.3 | ✅ The board feeds it 3.3 V, the top of the range. |
| 23 | Holding SDA low for 45 to 55 ms makes the part reset its bus interface | p.4 Note 7 | ✅ Relevant only if the bus hangs. |

## MPU6050 (IMU)

| # | Claim | Datasheet | Verdict |
|---|---|---|---|
| 24 | Address 0x68 with AD0 low, 0x69 with AD0 high | PS p.15; PS p.33 | ✅ |
| 25 | A floating AD0 gives a defined address | **Not stated.** | ⚠️ On this board AD0 reaches only the AD1 header (see the inventory). The firmware probes both addresses. |
| 26 | `WHO_AM_I` (0x75) reads 0x68 whatever AD0 is | RM p.46 | ✅ The firmware logs any other value and keeps reading, because compatible parts answer differently. |
| 27 | The part powers up asleep: `PWR_MGMT_1` (0x6B) resets to 0x40. Writing 0x01 wakes it with the clock on the PLL, X-gyro reference | RM p.8; RM p.41 | ✅ |
| 28 | `SMPLRT_DIV` (0x19): rate = gyro output rate / (1 + divider), and the gyro output rate is 1 kHz when the low-pass filter is on. Divider 4 → 200 Hz | RM pp.11–12 | ✅ |
| 29 | `CONFIG` (0x1A) `DLPF_CFG` 3: accelerometer 44 Hz with 4.9 ms delay, gyro 42 Hz with 4.8 ms delay | RM p.13 | ✅ |
| 30 | `GYRO_CONFIG` (0x1B) `FS_SEL` 0 = ±250 °/s, 131 LSB per °/s | RM p.14; PS p.12 | ✅ Scale-factor tolerance ±3% at 25 °C (PS p.12). |
| 31 | `ACCEL_CONFIG` (0x1C) `AFS_SEL` 0 = ±2 g, 16384 LSB/g | RM p.15; RM p.30 | ✅ |
| 32 | Registers 0x3B to 0x48 hold accel X/Y/Z, temperature, gyro X/Y/Z, each 16-bit two's complement, high byte first; a burst read of them comes from one sampling instant | RM p.7; RM p.30 | ✅ |
| 33 | `INT_PIN_CFG` (0x37) = 0 makes INT push-pull and active high; `INT_ENABLE` (0x38) = 0 enables no interrupt | RM pp.27–28 | ✅ That INT then stays low is our conclusion from those two facts, not a sentence in the document. It matters because the AD1 jumper ties AD0 to INT. |
| 34 | I2C up to 400 kHz; VDD 2.375 to 3.46 V; VIH = 0.7 × VLOGIC | PS p.15; PS p.7 | ✅ VDD and VLOGIC are both 3.3 V on the schematic. |
| 35 | Readings are valid immediately after waking | PS p.12: gyro zero-rate output settles to ±1 °/s 30 ms after power-on | ⚠️ Minor: the first few readings after boot are not settled. |

## Not covered by these datasheets (unverified)

- **ESP32 input-high threshold.** Whether the I2C bus's idle level is high enough for the ESP32
  depends on its VIH, which none of these documents give (same gap as MAX30003 check #20).
- **ESP32 ADC on IO27.** That ADC2 works while WiFi is off, and the range over which the ADC is
  linear at 11 dB attenuation, come from Espressif's documentation, not checked here.
- **LM324 output swing on a 3.3 V supply.** It sets the top of the GSR output range. Not checked;
  the first bench session measures it (open-header reading).
- **The schematic is the design, not the board.** Every pin and address here is confirmed only
  when the firmware's boot probe prints it.
