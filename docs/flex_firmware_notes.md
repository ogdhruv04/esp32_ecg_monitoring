# What `sketch.ino` will need for the ring flex board

Written 24 Nov 2026, before any flex board has been powered. Source: the schematic
`docs/HEALTH_FLEX_C3_WITH_BMS.pdf` (sheet 1 power, sheet 2 MCU / MAX30003 / sensors), read by
designator and U3 (ESP32-C3, QFN32) pin number, plus the datasheet pages cited below.
**No flex block has been added to `sketch.ino` yet**; this file lists what that block and the
code around it will need. The bring-up kit (`flex_bringup/`) checks the hardware first.

## 1. Pin block

A new `BOARD_FLEX_C3` block, tested **before** `CONFIG_IDF_TARGET_ESP32C3` (as `BOARD_TEST_C3`
is), and built by a `build_flex.sh` with `-DBOARD_FLEX_C3`:

| Define | Value | U3 pin, net | Note |
|---|---|---|---|
| `DEVICE_TAG` | `"FLEX"` | | |
| `MAX30003_CS_PIN` | 7 | pin 13 (MTDO), CS → U4 pin 15 CSB | same as the RING block |
| `MAX30003_INT1_PIN` | 10 | pin 16, INTB → U4 pin 21 | same as the RING block; U4 pin 20 (INT2B) is unconnected |
| SPI SCK / MISO / MOSI | 4 / 5 / 6 | pins 9 (MTMS) / 10 (MTDI) / 12 (MTCK) → U4 pins 16 / 18 / 17 | the C3's FSPI defaults, so `SPI.begin()` with no arguments works, as on the ring |
| `SYNC_PIN` | **-1** | | see below: **3 is taken** |
| `ENABLE_BLE` | 1 | | but see R5 in section 5 |
| `SENS_SDA_PIN` / `SENS_SCL_PIN` | 8 / 9 | pins 14 / 15 | strapping pins, section 4 |
| `GSR_ADC_PIN` | -1 | | no GSR front end on the flex |
| new: PPG interrupt | 3 | pin 8, `INT30102` | MAX30102 INT, open-drain, R17 4.7 kΩ to **1V8** |
| new: fuel-gauge alert | 18 | pin 25, `BM_ALRT` | MAX17055 ALRT, open-drain, R23 4.7 kΩ to 3V3 |
| new: charger enable | 19 | pin 26, `BC_EN` | **tied to GND through R21 (0 Ω)**: input only, section 5 |

**GPIO3 is the MAX30102 interrupt here, so the RING block's `SYNC_PIN 3` must not carry over.**
`setup()` does `pinMode(SYNC_PIN, INPUT_PULLDOWN)` and attaches a RISING interrupt
(`sketch.ino`, around line 330). On the flex that would:
- set the ESP32's internal pull-down against R17's pull-up to 1V8;
- log every MAX30102 interrupt edge as a `K` sync line, which would corrupt any alignment
  done from `K` lines.

There is no spare GPIO with a pad for SYNC: GPIO0/1 (pins 4/5, XTAL_32K) are marked
no-connect, GPIO2 (pin 6) has only its pull-up R6, and GPIO18/19 are used. So `SYNC_PIN` is
-1 and the two `SYNC_PIN` lines in `setup()` need an `#if SYNC_PIN >= 0` guard. Alignment
against another device stays software-only, from the beat trains, as it is today (CLAUDE.md:
no hardware sync is in use). If the hardware team wants a sync input later, a wire to the R6
node (GPIO2) is the only candidate. GPIO2 is a strapping pin: Espressif recommends it be high at
reset (ESP32-C3 datasheet v2.5, Table 3-3 note 2), so the sync source must not hold it low
across a reset.

For the MAX30102 itself, polling (as on the reference board, where INT is not routed) avoids
the logic-level question: INT idles at 1.8 V, below the C3's guaranteed V<sub>IH</sub> of
0.75 × VDD = 2.48 V (ESP32-C3 datasheet Table 5-4). The MAX30003's INTB and SDO have the same
1.8 V levels on the reference board and work there in practice (`docs/MAX30003_datasheet_check.md`
#20), so an interrupt on GPIO3 would probably work too, but it is out of spec.

## 2. Serial: CDCOnBoot off, UART at 460800

- The flex board has no USB: GPIO18/19, the C3's USB D−/D+, are `BM_ALRT` and `BC_EN`. Build
  with `CDCOnBoot=default` (disabled), so `Serial` is UART0 on the RX1/TX1 pads (U3 pins 27/28),
  read through a 3.3 V USB-UART adapter.
- `SERIAL_BAUD` stays 460800: this is a real UART, like the reference board's, so
  `capture.py --baud 460800`. The adapter must support it. The CLAUDE.md line about the C3
  ignoring the baud rate applies to the SuperMini's native USB, not to this board.
- `FlashMode=dio`, as on the custom C3 test board. The flash is in the package, so DIO is safe
  whatever the part.
- FQBN: `esp32:esp32:esp32c3:CDCOnBoot=default,FlashMode=dio`. Flash by hand, as in
  `flex_bringup/README.md` (no auto-reset; the BOOT pad is the one labelled "GND4").
- `serial_monitor.py` asserts DTR for the SuperMini's TinyUSB. That is harmless here, since DTR
  is not wired.

## 3. EN_RBIAS on

The flex has **two electrodes** (EGGP / EGGN → R7 / R8 51 kΩ → ECGP / ECGN, with C23 / C27
10 pF to GND and C25 1 nF across) and **no body-reference electrode**: VCM (U4 pin 24) is only
decoupled. The bench sessions showed that a reference is essential: removing the third clip took
the finger channel from 0.4% to 43% mains (CLAUDE.md, status). On a two-electrode board the
MAX30003's internal lead bias has to take that role.

- The library's `begin()` leaves `EN_RBIAS` = 00 (off), with RBIASV 100 MΩ and RBIASP = RBIASN
  = 1 already set (`CNFG_GEN = 0x081007`; `docs/MAX30003_datasheet_check.md` #10, #11,
  datasheet pp.32–34). `setRbias(true)` sets `EN_RBIAS` = 01 and reads it back.
- For `BOARD_FLEX_C3`, call `setRbias(true)` after `begin()` and after any input-configuration
  change that rewrites `CNFG_GEN`.
- The `b` command toggles from a `static bool rb = false`. Start it from the boot state, or the
  first `b` on the flex re-enables RBIAS instead of turning it off.
- This makes the flex's register config differ from the ring and the reference board by one
  field. The two-device study rests on identical config (CLAUDE.md), so the `# cfg` line should
  also print `CNFG_GEN`, and any flex-vs-chest comparison has to state that RBIAS was on.
- Still open and shared with the other boards: `begin()` routes the calibration sources onto
  the inputs (#21, `docs/amplitude_investigation.md`). Whether the flex boots in `d` or `e`
  follows that A/B result.
- RBIASV (50 / 100 / 200 MΩ) is a choice for the bench, not something to settle from the
  datasheet.

## 4. I²C on the strapping pins GPIO8 / GPIO9

- **GPIO9 (SCL) low at reset means download mode** (ESP32-C3 datasheet Table 3-3). The "GND4"
  pad is on this net for that reason. Anything that holds SCL low through a reset, a stuck
  slave or a solder bridge on that pad, stops the board from booting the firmware.
  **GPIO8 (SDA) must be high for download mode**; R10 (10 kΩ) sees to that.
- **LED D2 is on SDA**: anode through R9 (5.1 kΩ) to 3V3, cathode on GPIO8. It lights whenever
  SDA is low, so it flickers with bus traffic, and the firmware **cannot use it as a status LED
  while I²C runs**: turning it on holds SDA low and hangs the bus. Use it only before
  `Wire.begin()` or after `Wire.end()`, as `flex_bringup.ino` does.
- **Pull-ups to two rails**, as on the reference board (`docs/sensor_inventory.md`, open
  question 3). To 3V3: R10 / R3 10 kΩ, R18 / R15 and R25 / R24 4.7 kΩ. To 1V8: R14 / R13
  4.7 kΩ (at the MAX30102). On an idle bus, current flows from 3V3 into the 1V8 rail, which the
  TC1015 linear regulator cannot sink. `flex_bringup` measures 1V8 through GPIO3 (R17), so the
  first boards will show whether the rail rises.
- The firmware's existing I²C code carries over: it already probes the MPU6050 at both
  addresses (AD0, U6 pin 9, is unconnected here too), and the `f` command switches between 400
  and 100 kHz. One more part sits on the bus: the **MAX17055 at 0x36** (MAX17055 User Guide
  Rev 0, p.36). It has an internal 0.2 µA pull-down on SDA and SCL (its datasheet, p.5), which is
  negligible against the pull-ups.
- Addresses on this bus: 0x57 MAX30102, 0x48 MAX30205 (A0–A2 = GND), 0x68/0x69 MPU6050,
  0x36 MAX17055. No collisions.

## 5. Other things found on the schematic

For the hardware team, or for later firmware work. None of these blocks the bring-up kit.

- **R5 = 10 kΩ in series with the antenna feed** (sheet 2: ANT pin 2 → R5 → ANT_SIG → U3 pin 1
  LNA_IN, with C12 / C13 to GND on either side). This is the position of a π-match series
  element, normally 0 Ω or an inductor. If 10 kΩ is fitted as drawn, BLE range will be very
  short. Ask before drawing any conclusion from flex BLE tests.
- **GPIO19 (`BC_EN`) is tied to GND through R21 (0 Ω)** at the charger's active-low CE (sheet 1).
  Charging is therefore always enabled, and the firmware must never drive GPIO19 high. It is
  also the C3's USB D+ pin, which the USB-Serial-JTAG controller owns at reset. Whether that
  controller's pull-up draws current through R21 until GPIO19 is reconfigured needs the
  ESP32-C3 technical reference manual; it is not checked here.
- **Charger settings** (BQ25185, datasheet SLUSF65B): R20 = 39 kΩ on ILIM/VSET sits between the
  43 kΩ and 33 kΩ rows of Table 6-1, which both mean **V<sub>BATREG</sub> = 4.35 V**: right for a
  4.35 V cell, an overcharge for a standard 4.2 V one. R22 = 50 kΩ on ISET gives
  I<sub>CHG</sub> = K<sub>ISET</sub> / R<sub>ISET</sub> ≈ 300 AΩ / 50 kΩ = 6 mA (p.7, p.12). The
  datasheet recommends an extra RC on ISET below 50 mA (p.12). Confirm both against the ring's
  cell.
- **Pad "GND2" is the `BAT_TEMP` net, not ground**: TS/MR of the charger (R2 0 Ω) and THRM of the
  fuel gauge (R28 0 Ω). With no thermistor the pin floats. The datasheet says to fit 10 kΩ to GND
  when TS is not used (section 6.3.9, p.18), so check how charging behaves as drawn. The
  MAX17055's THRM, a thermistor-bias output, drives the same node.
- **Pad "GND4" is SCL / GPIO9**, the boot pad (section 4). Both misleading names are worth
  fixing on the silkscreen or in the documentation.
- **U3 pins 18–24 (VDD_SPI, SPIHD/WP/CS0/CLK/D/Q) are marked no-connect**, so the board needs
  a C3 **with in-package flash** (FN4 / FH4 / FH4AZ / FH4X / FH8X; ESP32-C3 datasheet
  Table 1-1). A plain ESP32-C3 has no flash and cannot boot here. The bring-up kit reports the
  flash ID.
- **R32**, the TC1015's SHDN pull-up, has no value printed.
- **Fuel gauge**: the MAX17055's SOC means little until the host writes its EZ configuration:
  DesignCap (18h), IChgTerm, VEmpty and ModelCfg (DBh) (User Guide Rev 0, pp.8–9 and p.22).
  The Status register's POR bit (p.25) tells the firmware when the part has reset and needs the
  configuration again. The ring cell's capacity is not in the schematic. The sense resistor is R31 = 10 mΩ, the value the register LSBs assume
  (datasheet Table 6). A `B,` line for cell voltage, SOC and current would follow the existing
  sensor-line pattern (`seq`, `ecg_index`, `micros`).
- The MAX30003's clock is a SiT1533 32.768 kHz oscillator (U5) on FCLK, and its digital I/O
  runs at 1V8 (OVDD), as on the reference board. The sample index remains the clock.
