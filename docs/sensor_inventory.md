# Extra sensors: inventory

What else is on the boards besides the MAX30003, where, and how sure we are. Written
10 Nov 2026 from three sources, none of which is a measurement:

- `docs/ESP32_health_schematic.pdf`: the reference board's schematic (Altium, dated 7/31/2025,
  one sheet). Added to the repo on 10 Nov 2026; before that it was only in Downloads.
- `MAX30102_MPU6050_MAX30205.ino`: the bring-up sketch for the three I2C parts.
- The note in `sketch.ino` that IO27 is `GSRSENSE`.

**Nothing here has been confirmed on hardware.** The firmware probes every part at boot and
prints what it found (`# sens ...` lines); that print is the confirmation, and step A of
`docs/bench_session_1.md` is where it gets read.

## Where each sensor is

All four are on the **reference board** (ESP32-WROOM-32D, custom PCB). The C3 test board's
schematic (`docs/ESP32C3_custom_schematic.pdf`) shows no sensor. There is no schematic of the
ring (ESP32-C3 SuperMini) in the repo; you confirmed on 10 Nov that only the reference board
has the sensors.

| Sensor | Part (ref. des.) | Bus | Pins on the ESP32 | Address | Supply, via | Interrupt pin |
|---|---|---|---|---|---|---|
| PPG, red + IR | MAX30102EFD+ (U8) | I2C | SDA **IO21**, SCL **IO22** | 0x57, fixed | VDD 1.8 V through header **HR1**; LEDs from 3.3 V directly | `INT30102` net: pulled up, **not routed** to the ESP32 |
| Temperature | MAX30205MTA+ (U5) | I2C, same bus | IO21, IO22 | 0x48 (A2 = A1 = A0 = GND) | 3.3 V through header **TEMP1** | OS: pulled up, not routed |
| IMU, accel + gyro | MPU6050 (U7) | I2C, same bus | IO21, IO22 | 0x68 or 0x69, see below | 3.3 V (VDD and VLOGIC) through header **GYRO1** | INT: goes only to header **AD1**, not to the ESP32 |
| GSR | LM324 front end (U4) + header **GSR1** | ESP32 ADC | **IO27** = ADC2 channel 7, net `GSRSENSE` | n/a | 3.3 V | n/a |

How the pins were read: by **module pin number**, not by where the net label sits. On the ESP32
symbol, `SDA` is on module pin 33 (IO21), `SCL` on pin 36 (IO22), `GSRSENSE` on pin 12 (IO27).
This is the schematic that was once misread for chip-select (IO4 against the measured IO5,
CLAUDE.md); by pin number, `CS` is on pin 29, which is IO5, so the same rule gives the right
answer there. IO21/IO22 are also the ESP32 Arduino core's default I2C pins.

You said on 10 Nov that all three ICs are soldered and the HR1, TEMP1 and GYRO1 jumpers are on.

### The bring-up sketch does not match this board

`MAX30102_MPU6050_MAX30205.ino` calls `Wire.begin(8,9)`. GPIO8/GPIO9 are the **ESP32-C3's**
default I2C pins (`variants/esp32c3/pins_arduino.h` in core 3.3.11) and are flash pins on a
WROOM module, so that sketch cannot have run on the reference board as written. You confirmed
the sensors are on the reference board only, so the sketch is used here for its settings alone
(the same three parts; MPU6050 at ±2 g and ±250 °/s; MAX30205 read as a plain temperature), not
for its pins. Its other choices were not carried over: it reads each sensor once a second with
`delay(1000)`, and it turns red/IR into "SpO2" with `110 − 25 × ratio`, which is not a
calibration of anything.

## What the firmware does with them

Details and line formats are in `sketch.ino` ("Extra sensors") and CLAUDE.md.

| Stream | Rate | Clock | Line |
|---|---|---|---|
| PPG | 100 samples/s, red and IR, 18-bit | the MAX30102's own oscillator; FIFO polled after every ECG drain | `P,ppg_index,ecg_index,micros,red,ir` |
| IMU | one reading per 4 ECG samples = 64 Hz | ECG | `M,seq,ecg_index,micros,ax,ay,az,gx,gy,gz` |
| GSR | one reading per 16 ECG samples = 16 Hz, each the sum of 8 ADC reads | ECG | `G,seq,ecg_index,micros,adc_sum,mv_sum` |
| Temperature | one reading per 256 ECG samples = 1 Hz | ECG | `T,seq,ecg_index,micros,raw` |

Every line carries the ECG sample index it was taken at and the ESP32's `micros()`. Sensor work
runs only after the ECG FIFO has been drained, and a sensor that stops answering is switched
off after 8 failed transactions so it cannot stall the ECG.

## The GSR circuit, as drawn

Read from the schematic; **no value below is measured**.

- R5/R12 (4.7 kΩ each) halve 3.3 V to a 1.65 V reference, filtered by C6.
- **GSR1** is the electrode header: pin 2 is board ground, pin 1 goes through R13 (200 kΩ) to
  the reference. So the skin sits between pin 1 and ground, and the voltage on pin 1 is
  `V_skin = 1.65 V × R_skin / (R_skin + 200 kΩ)`. U4B buffers it.
- A second 200 kΩ (R9) from the reference meets the trimmer R6, wired as a variable resistor to
  ground: `V_trim = 1.65 V × R6 / (R6 + 200 kΩ)`. U4A buffers it. **R6 has no value on the
  schematic.**
- U4C combines them: R8 (100 kΩ) from U4A to the inverting input, R7 (200 kΩ) feedback, U4B
  into the non-inverting input through R15 (100 kΩ) with nothing to ground. That is
  **`V_out = 3 × V_skin − 2 × V_trim`**.
- R10 (marked "1ML", read as 1 MΩ) and C7 (100 nF) low-pass the output at about 1.6 Hz before
  `GSRSENSE` reaches IO27.

Consequences worth knowing before the bench:

- **More skin conductance means a lower voltage.** A response to a deep breath (sweat glands
  fill, resistance drops) should show as a **fall** in `mv_sum`. The check in the bench plan is
  on the size of the move; the sign it finds is the first test of this reading.
- Header open (no electrodes): `V_skin` = 1.65 V, so the output is driven to its upper limit
  for most trimmer settings. Header shorted: `V_skin` = 0, output at the bottom. A fixed
  resistor across the header gives a predictable value in between. These three are the circuit
  test in the bench plan and do not need skin.
- The firmware reports millivolts at the ADC pin. Converting to conductance needs R6's setting
  and a check of this transfer function against known resistors. Not done.

## What I could not determine

Answered by you on 10 Nov 2026, kept here for the record:

- Which boards have the sensors → reference board only.
- Whether the three ICs are fitted and powered → all soldered, HR1/TEMP1/GYRO1 jumpers on.

Still open. None of these blocks the firmware (it probes rather than assumes), but each
changes what the bench session should expect:

1. **Is the board built as the schematic says?** The chip-select line was debated once already.
   Settled by the boot lines `# sens ppg: ... part:15 ... ok`, `# sens imu: addr:68 whoami:68 ... ok`
   and `# sens temp: addr:48 cfg:00 ... ok`.
2. **MPU6050 address: 0x68 or 0x69?** AD0 is not tied to a supply rail. It runs to pin 1 of
   header AD1, and pin 2 of AD1 is the INT pin. With a jumper on AD1, AD0 follows INT, which
   the firmware keeps low (address 0x68). With AD1 open, AD0 floats and the address is not
   defined; it could even change while running. **Is there a jumper on AD1?** If the IMU shows
   `err:` counts or gets disabled, this is the first suspect.
3. **Mixed pull-up voltages on the I2C bus.** SDA and SCL each have three 4.7 kΩ pull-ups: two
   to 3.3 V (R14/R16 at the MAX30205, R20/R21 at the MPU6050) and one to the MAX30102's 1.8 V
   supply (R22/R24). With all three jumpers on, the idle bus level works out to 2.8 V
   ((2 × 3.3 + 1.8) / 3), and about 0.2 mA per line flows from 3.3 V **into the 1.8 V rail**,
   which a linear regulator cannot absorb unless the 1.8 V loads draw more than that. The
   MAX30102's own pins tolerate it (datasheet check #15). **Unknown: whether 2.8 V is a solid
   high for the ESP32, and whether the 1.8 V rail stays at 1.8 V.** The MAX30003 and MAX30102
   are both on that rail and the MAX30102's absolute maximum is 2.2 V. Measure the rail with a
   multimeter in step A.
4. **What is connected to GSR1?** You were not sure. The check needs two skin electrodes there.
5. **R6's value and setting**, and the LM324's highest output on a 3.3 V supply. Together they
   decide whether the GSR output sits in range or pinned at a limit with electrodes on.
6. **Can GSR electrodes be worn together with the ECG electrodes of the same board?** GSR1
   pin 2 ties the skin to board ground through the electrode, while the MAX30003 holds the body
   at its own bias through the third ECG electrode. Two different DC levels on one body could
   disturb the ECG. Unknown; step B4 of the bench plan compares the ECG with the GSR electrodes
   off and on before the long capture depends on it.
7. **Which finger goes where.** The MAX30102, the ECG finger electrodes, the GSR electrodes and
   the MAX30205 are all meant for fingers of what may be the same hand. Where each sits on the
   PCB, and whether one hand can reach them all at once, I cannot tell from a schematic.
8. **What the MAX30205 touches.** It is a board-mounted part with no probe. Whether it reads
   skin, or the temperature of the PCB next to a regulator, depends on the layout.
9. **The MAX30102's true sample rate.** Set to 100 per second; the datasheet gives no tolerance
   (check #16). Measured against the ECG clock in every capture from now on.
