# Bench session plan: polarity, calibration source, 10-minute dual capture

One session, three steps, in this order. Each step answers a question that the next one
depends on. Register facts are from the MAX30003 datasheet, Rev 3, pp.35–36
(`docs/MAX30003_datasheet_check.md`, #21 and #23).

**Safety:** the laptop runs on battery for the whole session (unplug the charger before any
electrode touches skin). Both boards are powered from the laptop's USB, so they share a ground
through it (CLAUDE.md, Rules).

## Before the session: firmware prerequisite (not yet done)

The firmware cannot change the input multiplexer or the calibration source at run time; its
only serial commands are `b` (body bias) and `r` (FIFO reset). Step 2 needs three more, added
to `sketch.ino` and flashed to **both** boards (one sketch, never forked):

| Command | `CNFG_EMUX` (0x14) | `CNFG_CAL` (0x12) | Meaning |
|---|---|---|---|
| `d` | `0x0B0000` | `0x720000` | Today's configuration from the library's `begin()`: electrodes connected (OPENP = OPENN = 0) **and** the calibration sources switched onto both inputs (CALP_SEL = VCALP, CALN_SEL = VCALN) |
| `e` | `0x000000` | `0x000000` | Electrodes only: inputs connected, no calibration source, calibration disabled |
| `c` | `0x390000` | `0x702800` | Scale test: electrodes disconnected (OPENP = OPENN = 1), ECGP ← VCALP, ECGN ← VMID; VCAL on, bipolar, VMAG 0.5 mV, FCAL ≈ 16 Hz, 50% duty |

Each command should be followed by FIFO_RST and a `#` line echoing both registers read back,
so every capture log records the configuration it was taken in.

Bit fields used (pp.35–36): `CNFG_EMUX` D23 POL, D21 OPENP, D20 OPENN, D[19:18] CALP_SEL
(01 VMID, 10 VCALP, 11 VCALN), D[17:16] CALN_SEL. `CNFG_CAL` D22 EN_VCAL, D21 VMODE
(1 = bipolar: VMID ± VMAG), D20 VMAG (1 = 0.50 mV), D[14:12] FCAL (010 ≈ 16 Hz), D11 FIFTY.

## Step 1. Swap the clips (≈10 min)

**Do:** on both 3-wire cables, swap the two non-reference clips. Leave the reference clip
where it is. Then a 60 s dual capture at rest:
`./capture_dual.py --seconds 60 --label s1_polarity`, then
`./fiducial.py dual captures/<stamp>_s1_polarity_ring.csv captures/<stamp>_s1_polarity_ref.csv --chest ring`.

**Answers:** is the recording now upright lead II? `fiducial.py` prints each channel's
whole-recording polarity. It must read **+1 on both**, where dual03 read −1 on both
(`analysis/fiducial_*dual03*_v2.txt`).

**Why first:** every later capture, and every morphology or amplitude claim, should be in
standard polarity. The new timing point (tp2) finds the sign itself, so detection does not
depend on this; the readability of every trace and figure does.

## Step 2. Calibration-source test, #21 and #23 (≈30 min)

**2a. Does the calibration source load the electrode signal? (#21)**
Electrodes on, at rest. On one board at a time, capture 60 s in configuration `d`, then 60 s
in `e`, then `d` again (the repeat shows drift between captures). Label them
`s2a_<board>_d1`, `s2a_<board>_e`, `s2a_<board>_d2`.

*Hypothesis:* `CNFG_CAL = 0x720000` has FIFTY = 0 and THIGH = 0, so the sources sit at one
level (tHIGH = 0) and are switched onto the same input nodes as the electrodes. A
low-impedance source on that node would load the ~50 kΩ electrode path, shrinking the ECG.
*Prediction if true:* the median R amplitude in `e` is clearly larger than in both `d`
captures. *If false:* the three amplitudes agree within the d1–d2 difference.

**2b. Is the code-to-millivolt scale right? (#23)**
Electrodes can stay attached; configuration `c` disconnects them internally. Capture 60 s in
`c` on each board (`s2b_<board>_cal`).

*Prediction from the nominal scale* (1 mV = 2621.44 codes at gain 20, formula from the
MAX30001 datasheet): each edge of the ±0.5 mV square wave is a 1.0 mV step, **≈2,621 codes**.
Measure the step as the mean of the samples just after each edge has settled minus the mean
just before it, over all edges. The on-chip 0.5 Hz high-pass and 40 Hz low-pass bias that by a
few percent at 16 Hz, which does not matter here: the open question is a factor of about ten
(dual03 spans 0.136 / 0.153 mV under the nominal scale, `analysis/nominal_mv_scale_dual03.txt`
on the `ui-redesign` branch), not a few percent. A small script for this measurement still has
to be written.

**Together, 2a and 2b answer:** why is the signal so small? Scale right and `e` larger → the
calibration routing attenuates, and `e` (or OPENP/OPENN-correct settings) becomes the default.
Scale wrong → amplitudes need a corrected factor. Both fine → the electrodes/skin path is the
cause. **Step 3 uses whichever configuration step 2 shows is right**, so decide before starting
it, and put the configuration in the capture label.

## Step 3. 10-minute dual capture at rest (≈20 min)

**Do:** laptop on battery, both boards, chest on one, finger on the other, seated, hands still.
`./capture_dual.py --seconds 600 --label s3_rest10_<config>`, then
`./integrity.py`, `./agreement.py` and `./fiducial.py dual` on the pair.

**Answers:**
- **Does tp2 hold up on a second, longer recording?** The timing-point result currently rests on
  one 105 s recording (dual03). This gives ~6× the beats from a fresh session.
- **What is the oscillator drift between the boards?** Over 105 s the drift estimate's standard
  error was 10.3 ppm (`analysis/agreement_20260929_163314_*_ref.txt`), too large to test the
  ±20 ppm assumption. The standard error of a slope falls as T^1.5, so 600 s should bring it to
  about 10.3 / (600/105)^1.5 ≈ 0.75 ppm.
- **Is the host-clock rate anomaly real?** The link test ran at 256.04 SPS mid-capture but
  255.1 SPS overall (`analysis/integrity_20260929_152557_linktest_noelectrodes.txt`). A 10-minute
  run shows whether the lag again builds only at the ends.
- **More data** for calibrating the quality gate, which has seen three recordings.

## After the session

Commit the captures and their analysis files. Update CLAUDE.md's status section with the
polarity result, the #21/#23 outcome (and the datasheet check file), and the drift figure.
