# MAX30003 claims checked against the datasheet

Source: `docs/MAX30003 - Ultra-Low Power, Single-Channel Integrated Biopotential (ECG, R-to-R Detection) AFE - MAX30003.pdf`,
Analog Devices **Rev 3, 9/21**, 46 pages. The printed page numbers match the PDF page numbers.
Checked 21 Sep 2026. Register values decoded bit by bit against the tables cited.

Verdicts: ✅ confirmed · ❌ we had it wrong (corrected) · ⚠️ datasheet raises an issue that needs a hardware test

| # | Claim | Datasheet | Verdict |
|---|---|---|---|
| 1 | ECG FIFO is 32 words × 24 bits | p.41 | ✅ |
| 2 | FIFO word: `[23:6]` 18-bit two's-complement sample, `[5:3]` ETAG, `[2:0]` PTAG | p.41 Table 32; p.42 | ✅ |
| 3 | ETAG `000` valid, `010` valid + last in FIFO, `110` empty, `111` overflow → issue `FIFO_RST` | p.42 Table 33 | ✅ |
| 4 | ETAG `001` / `011` (fast-recovery mode) are **valid samples** | p.42 Table 33: *voltage NOT valid*, time step valid | ❌ Corrected in code comments. 0 of 123,762 samples across all post-fix captures carry ETAG 1 or 3, so no existing data is affected. The firmware still sends these values over BLE untagged. |
| 5 | Overflow is cleared by `FIFO_RST` or `SYNCH` | p.41; p.26 Table 8 | ✅ |
| 6 | EOVF clears when STATUS is read (old firmware comment) | p.26 Table 8: EOVF *remains active until FIFO_RST or SYNCH* | ❌ Comment corrected. Firmware behaviour was already right (it issues FIFO_RST on overflow). |
| 7 | `EN_INT`: EN_EINT = D23, EN_EOVF = D22, INTB_TYPE = D[1:0] (00 three-state, 01 CMOS, 10 open-drain, 11 open-drain + internal 125 kΩ); default 11 | p.28 Tables 9–10 | ✅ So `0xC00001` = EINT + EOVF + CMOS push-pull. |
| 8 | `MNGR_INT`: EFIT = D[23:19], asserts at EFIT+1 unread records; `0x180004` → EFIT 3 → **4** records; D2 CLR_SAMP = 1 self-clears | p.29 Tables 11–12 | ✅ |
| 9 | STATUS lead-off bits LDOFF_PH/PL/NH/NL = D[3:0]; D[11:8] = LONINT/RRINT/SAMP/PLLINT; `0x000200` = SAMP | p.26–27 Tables 7–8 | ✅ |
| 10 | `CNFG_GEN` EN_RBIAS = D[5:4], `01` = on (only if EN_ECG is set) | p.32–33 Tables 20–21 | ✅ |
| 11 | Library `begin()` writes `CNFG_GEN = 0x081007` → FMSTR 00 (32 768 Hz), EN_ECG 1, EN_DCLOFF 01, DCLOFF_IMAG 000, VTH ±300 mV, EN_RBIAS 00 (off), RBIASV 100 MΩ, RBIASP = RBIASN = 1 | p.33–34 Table 21 | ✅ |
| 12 | The `leadoff` CSV column indicates electrode contact | p.33: IMAG `000` = *0 nA, disable and disconnect current sources* | ⚠️ DC lead-off is enabled but runs with no detection current. Don't treat the column as a contact indicator until an unplugged-electrode test shows it firing. |
| 13 | With FMSTR 00, RATE `01` = exactly 256 SPS and `10` = 128 SPS; `0x805000` → 128 SPS | p.34 Table 22; p.37 Table 28 | ✅ |
| 14 | On-chip filters: DHPF 1 = 0.5 Hz, DLPF 01 = 40.96 Hz at 256 SPS | p.38 Tables 28–29 | ✅ Also: at the old 128 SPS rate this low-pass was 28.35 Hz, not 40. |
| 15 | Channel gain | p.37 Table 28: `0x805000` → GAIN 00 = **20 V/V**, the lowest setting | New fact, not previously stated anywhere. |
| 16 | INFO reads `0x5?????`; `0x513261` → revision ID 1 | p.32 Tables 18–19 | ✅ Note: INFO is not valid if it is the *first* command after power-up or SW_RST. |
| 17 | Requires an external 32.768 kHz FCLK | p.4, p.7 | ✅ |
| 18 | SPI: ≤ 12 MHz, CPOL = 0 / CPHA = 0; the library uses 2 MHz, mode 0 | p.7 (fSCLK); p.21 | ✅ |
| 19 | Driving CSB/SCLK/SDI from a 3.3 V ESP32 while OVDD = 1.8 V risks injecting current into the 1.8 V rail | p.3 abs max: CSB, SCLK, SDI, FCLK rated −0.3 V to **+3.6 V regardless of OVDD**; p.6 VIH = 0.7 × OVDD | ✅ The concern is retired for these inputs. |
| 20 | The ESP32 reads SDO/INTB reliably | p.6: VOH = OVDD − 0.04 V ≈ 1.76 V when OVDD = 1.8 V | ⚠️ Works in practice. Whether it is *in spec* depends on the ESP32's VIH, which this datasheet does not cover. |
| 21 | ECG inputs are connected only to the electrodes | p.36 Table 26; p.35 Table 24. Library writes `CNFG_EMUX = 0x0B0000` → OPENP = OPENN = 0 (electrodes connected) **and** CALP_SEL = 10 (VCALP), CALN_SEL = 11 (VCALN). `CNFG_CAL = 0x720000` → EN_VCAL 1, bipolar, 0.5 mV, FCAL 000, FIFTY 0, THIGH 0. p.35: *"if a VCAL source is applied to a connected device, it is recommended that the appropriate channel MUX switches be placed in the OPEN position."* | ⚠️ **Open.** On both boards the calibration sources are routed onto the inputs alongside the electrodes. We still record recognisable ECG, so the electrodes get through, but the effect on amplitude and noise is unknown. Needs a hardware A/B test with `CNFG_EMUX = 0x000000`. |
| 22 | Changing CNFG_ECG after `begin()` | p.37: changes may cause discontinuities, and SYNCH restores synchronisation | ⚠️ Minor. We change RATE after `begin()`'s SYNCH and follow with FIFO_RST, not SYNCH. Measured rate is 256.00 SPS, so no visible effect. |
| 23 | ADC code → millivolts at the electrodes: `mV = code × VREF / (2^17 × GAIN)`, so at VREF 1000 mV and GAIN 20, 1 LSB = 0.3815 µV and 1 mV = 2621.44 codes | **Not stated in this datasheet** (checked 23 Oct 2026). p.42 gives only the format (18-bit, left-justified two's complement); p.5 gives VREF = 1.000 V typ (0.995–1.005 V); p.37 Table 28 gives GAIN 00 = 20 V/V; p.3 gives an AC differential input range of ±32.5 mV at AVDD 1.8 V (×20 = ±650 mV, inside ±VREF, so the formula is at least consistent). The formula itself is from the sibling MAX30001 datasheet. | ⚠️ **Nominal, unverified on our boards.** Fine for display scaling if labelled nominal; not for amplitude claims. Under it, dual03's raw span is only 0.136 mV (chest) / 0.153 mV (finger) (`analysis/nominal_mv_scale_dual03.txt`), well below a typical R wave, so either the scale or the signal path (see #21) is suspect. To verify: open the inputs (OPENP = OPENN = 1), route VCAL with a known VMAG (p.35 Table 24, Figure 10) and compare the measured step in codes with the prediction. |

## Not covered by this datasheet (still unverified)

These need the ESP32 / ESP32-C3 datasheets, or a measurement:
- ESP32 internal pull-up of ~45 kΩ
- ESP32 VIH (see #20)
- Strapping pins (IO12 etc.)
- The ±20 ppm drift of the 32.768 kHz clock. The MAX30003 takes FCLK from outside, so the figure depends on each board's oscillator part.
