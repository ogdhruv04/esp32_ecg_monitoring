# Amplitude investigation: why is the ECG so small?

Desk work, 16 Nov 2026 (`fw` branch). No hardware was touched. Datasheet pages are the
MAX30003 Rev 3 PDF in `docs/`; our numbers are from the files named beside them.

## Summary

- **The problem is larger than the 0.14 / 0.15 mV figure suggests.** Those are raw spans
  that include baseline wander. The QRS of the median beat in dual03 is **103 µV peak-to-peak
  at the chest and 38 µV at the fingers** on the nominal scale (`analysis/amplitude_dual03.txt`).
  A standard limb lead is about ten times that.
- **The datasheet supports the loading mechanism but gives no number for it.** It draws the
  calibration source as a voltage source sitting directly on the amplifier input (Figure 3,
  p.15), says the input switches *must* be opened when it is used on a connected subject
  (p.16), and specifies no output impedance or drive strength anywhere. How much it
  attenuates therefore cannot be worked out at the desk.
- **Our recordings do not settle it.** They make a wrong code-to-millivolt scale unlikely
  (the electrode-free noise floor matches the datasheet's amplifier noise on the nominal
  scale). They do not separate "the calibration source loads the input" from "the signal is
  genuinely small at these electrode positions". The noise in dual03 leans slightly towards
  the second; the placement fact below leans towards the first.
- **The finger clips were on different hands** (Dhruv, 16 Nov), so the finger pair is a
  lead-I-like lead and 38 µV is far too small for it. Both sites, on two boards, are then
  about ten times low. One shared cause is more likely than two unlucky placements, and what
  the boards share is the chip configuration. Loading is the leading suspect; it is still
  unproven.
- **The 10-minute bench test below separates all three**, with the decision rules written
  down before the data. The firmware option that boots in `e` is built and is not the
  default.
- **The software is not the cause.** The raw codes leaving the chip are already small, and the
  app draws them on the same nominal scale (`EcgTrace.kt`, `NOMINAL_CODES_PER_MV`): at
  40 mm/mV a 38 µV QRS is 1.5 mm tall and a 103 µV one 4.1 mm.

## What `begin()` leaves, and how it could attenuate

The library writes `CNFG_EMUX = 0x0B0000` and `CNFG_CAL = 0x720000` (decoded in
`MAX30003_datasheet_check.md`, #21):

- OPENP = OPENN = 0: both series switches closed, electrodes connected (p.36).
- CALP_SEL = 10, CALN_SEL = 11: ECGP is also connected to VCALP and ECGN to VCALN (p.36).
- EN_VCAL = 1, bipolar, VMAG = 0.50 mV, FCAL = 000 (FMSTR/128, 256 Hz), FIFTY = 0,
  THIGH = 0 (p.35). The programmed high time is zero, so each source sits at one level.
  Whatever is left at 256 Hz lands on DC when sampled at 256 SPS, and the 0.5 Hz high-pass
  removes DC. **So this configuration adds no visible waveform**, which is why it went
  unnoticed.

Figure 3 (p.15) puts the calibration source on the amplifier side of the series switch. With
the switch closed, each amplifier input node is fed by two sources at once:

```
 electrode ── Ze ── Rs ──┬── amplifier input (1500 MΩ differential, 45 GΩ common-mode, p.3)
                         │
        VCAL (constant) ─┴─ Rcal        Rs = series resistor on the board, Rcal = the
                                        calibration source's output impedance (unknown)
```

The ECG reaches the amplifier scaled by **A = Rcal / (Rcal + Rs + Ze)** on each side. The
constant VCAL only adds DC. In configuration `e` the source is disconnected, the node sees
only the amplifier's own input impedance, and A is 1.

Two consequences follow if Rcal is small:

1. **Attenuation.** On the reference board Rs is 49.9 kΩ on each input (R23, R28 in
   `docs/ESP32_health_schematic.pdf`). An Rcal of 5 kΩ would give A = 5 / 54.9 = 0.09 before
   any electrode impedance is counted. The ring board's breakout has no schematic in the
   repo, so its Rs is unknown.
2. **Common-mode conversion.** If the two sides have different Rs + Ze, they are scaled
   differently, and a voltage common to both electrodes (mains) partly turns into a
   difference. The amplifier's high input impedance exists to prevent exactly this (p.1,
   "common-to-differential mode conversion").

The current this drives into the wearer is not a safety concern: at most 1 mV across
2 × 49.9 kΩ, about 10 nA on the reference board, inside the 5–100 nA the chip's own lead-off
sources use (p.4).

## What the datasheet says about the source's drive

| Where | What it says | What it tells us |
|---|---|---|
| p.15, Figure 3 | "CAL VOLTAGE" is drawn as a voltage source referenced to VMID, through a switch, onto the line to the amplifier input, after the series isolation switch. No series element is drawn. The lead-bias block beside it *is* drawn with its resistor (50–200 MΩ). | As drawn, a routed source competes directly with the electrode at the amplifier input. A block diagram is not a circuit, so this is suggestive only. |
| p.16, Calibration Voltage Sources | "When applying calibration voltage sources with the device connected to a subject, the series input switches must be disconnected so as not to drive signals into the subject." | The source can drive the electrode node. `begin()` does what this sentence forbids. |
| p.35, CNFG_CAL | "if a VCAL source is applied to a connected device, it is recommended that the appropriate channel MUX switches be placed in the OPEN position." | The same instruction, as a recommendation. |
| p.5, EC table and Note 9 | Magnitude 0.25 / 0.50 mV, error ±2%, "as applied to the ECG input, not as measured through the ADC channel". | The level is specified at the input node. It is stiff compared with the amplifier's input impedance, which is a very weak bound. |
| Whole document | **No output impedance, drive current or load specification for VCALP / VCALN.** (The 100 kΩ on p.5 is the VBG pin, not this source.) | Rcal is unknown. |

Our own data adds one bound: ECG does get through in `d` on a board with 49.9 kΩ in series,
so the source is not ideal (Rcal is not zero).

Not from the datasheet, and from memory only: the library's two values look like the ones in
Maxim's own demo code. If so, the vendor expected ECG to survive this configuration. I have
not checked this.

## Evidence in our recordings

All from `d` (there is no other configuration on file yet).

| Observation | File | For or against loading |
|---|---|---|
| QRS of the median beat: 270 codes = 103 µV (chest, ring board), 100 codes = 38 µV (fingers, reference board). The raw spans of 357 / 402 codes include baseline wander; at the fingers most of the span is wander. | `analysis/amplitude_dual03.txt`, `analysis/nominal_mv_scale_dual03.txt` | Consistent with it, and with a genuinely small signal. Does not separate them. |
| With no electrodes, the ring board's output has sd 1.42 codes = 0.54 µV. The datasheet's amplifier noise is 0.53 µV rms typical, 1.0 max (0.05–40 Hz, gain 20, p.4). The reference board reads 3.22 codes with 69.8% of its power at mains; the rest is 3.22 × √(1 − 0.698) = 1.8 codes. | `analysis/amplitude_linktest_noelectrodes.txt` | **Against a wrong scale.** If the true scale were 7–10 times coarser, which is what would make our ECG normal-sized, this floor would be 3.8–5.4 µV, four to five times the datasheet maximum, on two boards. |
| The same capture: open inputs, lead bias off, lead-off current 0 nA (#11, #12), and the output sits quietly at the amplifier's floor. | same | Weakly for. Nothing except the calibration sources gives those nodes a DC path, so the sources appear to hold them. This says Rcal is far below the gigaohms of an open input. It does not say Rcal is small next to 50 kΩ. There is no `e` capture to compare with. |
| With electrodes on, the part of the signal that does not repeat from beat to beat is 14.1 codes rms (5.4 µV) at the chest and 6.3 codes (2.4 µV) at the fingers. By the first-difference estimate the chest reads 7.5 codes against 0.79 for the same board with no electrodes. | `analysis/amplitude_dual03.txt`, `analysis/amplitude_linktest_noelectrodes.txt` | **Leans against loading as the whole story.** Body-side noise is clearly visible above the amplifier's floor, and loading scales it together with the ECG. If a 1 mV chest QRS had been cut to 103 µV, the true noise would be about 30–50 µV rms, a lot for someone sitting still. At face value, 3–5 µV of noise is ordinary and the QRS is small. The estimate is an upper bound on noise (it contains beat-to-beat T-wave variation: the heart rate was about 102 bpm), which weakens but does not remove the point. |
| The chest QRS is 19 times the noise and the finger QRS 16 times. | `analysis/amplitude_dual03.txt` | Loading does not change this ratio; a small projection of the heart's field does. A good chest lead is usually far better than 19. Same lean as the row above. |
| The raw mean is −117 codes on both boards with electrodes and −119 / −91 without. | both files | Neither. It is not the sources' DC (the high-pass removes that) and it does not depend on electrodes. Unexplained; watch whether it moves in `e`. |
| Chest and fingers, on two different boards, are both small. | `analysis/amplitude_dual03.txt` | Neutral. The boards share the firmware configuration, and the two sites are both non-standard leads. |

## Expected amplitude for our placements

`docs/Finger_vs_Chest_ECG_Result.docx` says only that the chest pair "is not a clinical
Lead II" and the finger pair "is not a clinical Lead I". The finger clips were on different
hands (Dhruv, 16 Nov), which is the second row below. **The chest positions and spacing are
still not recorded.**

| Placement | Expected QRS | Source | Ours, nominal |
|---|---|---|---|
| Standard lead II (right arm to left leg, or the torso equivalents) | R wave about 1 mV typical; one reference table gives 1.5 mV with 0.5 mV as the lower normal limit. Below 0.5 mV peak-to-peak in every limb lead is clinically "low voltage". | [1], [2], [3] | chest 0.103 mV: about 10 times below typical, 5 times below the low-voltage line |
| Lead I (one hand to the other: a ring touched by the opposite hand) | A limb lead, usually smaller than lead II. I have no sourced range; from memory 0.3–1 mV. | from memory, unchecked | fingers 0.038 mV: 13 times below the 0.5 mV low-voltage line |
| Two chest electrodes a few centimetres apart | 0.7–2.33 mV across the bipolar leads of one 36-patient study, about 1.9 mV at 8.7 cm over the left ventricle; amplitude falls as the spacing shrinks. A 6 cm pair still gives a usable signal. | [4], [5] | chest 0.103 mV: 7 times below the bottom of that range |
| Both finger clips on the same hand (not our case) | Tens of microvolts: both electrodes are far from the heart and close together. | from memory, unchecked | — |

So both amplitudes are anomalous: the chest for every chest placement I can find figures for,
and the fingers for a hand-to-hand lead. The on-chip
40 Hz low-pass also shaves the R peak; that is not quantified here and cannot be a factor of
five.

## Ranked hypotheses

| # | Hypothesis | What supports it | What weakens it | Test |
|---|---|---|---|---|
| 1 | **The calibration sources load the inputs** (#21). | The datasheet forbids this configuration on a connected subject and draws the source on the amplifier node. Both boards are affected, as a shared register setting would be. | No impedance figure exists. The noise argument above: it would require 30–50 µV of true body noise at rest. | `d` / `e` A/B, step 1 below. |
| 2 | **The signal is genuinely small at these electrode positions.** | Noise level and QRS-to-noise ratio look like an ordinary small lead. Both leads are known to be non-standard. | The chest reads below every published short-spacing figure I found, and the fingers were on different hands, so it would take two independent placements both ten times low. | Placement facts, then the wide-lead control, step 4 below. |
| 3 | **The code-to-millivolt scale or the gain is not what we assume** (#23, #15). | The formula is from the MAX30001 datasheet, and no capture log records `CNFG_ECG` read back. | The electrode-free noise floor matches the datasheet on the nominal scale. | `c`, step 2 below. It measures scale and gain together. |
| 4 | Something in the electrode path of both boards (cable, clips, the 49.9 kΩ with dry contact). | — | In `e` the amplifier's input impedance is 1500 MΩ (p.3), so series resistance of this size costs nothing. | Only if 1–3 all fail. |

Hypotheses 1 and 2 can both be partly true. The A/B test measures the size of 1 directly, and
whatever is left after it belongs to 2.

## Bench A/B protocol (10 minutes)

**Before the clock starts:** both boards flashed with the current `fw` image (the default
build: `d` / `e` / `c` are in it; neither board has them yet), laptop **on battery**, both
3-wire cables on, electrodes where they were for dual03 (chest on the ring board, fingers on
the reference board). Write down where every clip is and photograph it. Sit still.

Terminal A captures; terminal B sends commands. **Start each capture first, then send the
command within 5 s**, so that a board that resets when its port opens cannot silently fall
back to `begin`. The analysis drops the first 15 s of every file.

```bash
# terminal B, for mode X in d / e / c:
printf X > /dev/ttyACM0; printf X > /dev/ttyUSB0
```

| Min | Step | Terminal A | Mode |
|---|---|---|---|
| 0–5 | **1. A/B, electrodes on** | `./capture_dual.py --seconds 50 --label ab_d1`, then `ab_e1`, `ab_d2`, `ab_e2`, `ab_d3` | d, e, d, e, d |
| 5–6 | **2. Scale** (electrodes can stay on; `c` disconnects them inside the chip) | `./capture_dual.py --seconds 50 --label ab_c` | c |
| 6–7.5 | **3. Idle**: unplug both electrode cables from the boards | `./capture_dual.py --seconds 30 --label ab_idle_d`, then `ab_idle_e` | d, e |
| 7.5–10 | Read out (below) | | |
| +3 | **4. Wide-lead control**, only if step 1 shows no change: cables back in, mode `e` or `d` as decided, ring board's two measuring clips moved to right collarbone and left lower ribs, reference board's to one finger of each hand | `./capture_dual.py --seconds 40 --label ab_wide` | as decided |

Read-out:

```bash
grep -h "cfg" captures/*_ab_*.log | sort | uniq -c      # every file's mode, read back from the chip
./amplitude_check.py --skip-s 15 captures/*_ab_[de][123]_ring.csv --label ab_ring
./amplitude_check.py --skip-s 15 captures/*_ab_[de][123]_ref.csv  --label ab_ref
./amplitude_check.py --cal  --skip-s 15 captures/*_ab_c_r*.csv    --label ab_c
./amplitude_check.py --idle --skip-s 15 captures/*_ab_idle_*.csv  --label ab_idle
```

A file whose log shows any `# cfg` line with the wrong mode after the first 15 s is
discarded. `index_gaps` must be 0 in every row.

### Decision rules, fixed before the data

Per board, let **ρ** = median `qrs_pp_codes` of the two `e` captures ÷ median of the three
`d` captures, and **s** = largest ÷ smallest of the three `d` captures (what sitting still
for five minutes does on its own).

| Result | Conclusion | Action |
|---|---|---|
| ρ ≥ 1.5 **and** ρ > 1.2 × s, on both boards | Hypothesis 1 confirmed; the loading factor is 1/ρ. On the reference board, Rcal = (49.9 kΩ + Ze) / (ρ − 1). | `e` becomes the default, provided `qrs_pp/noise` in `e` is not lower than in `d`. Repeat the link test and the dual capture in `e`. Close #21. |
| ρ between 1/s and s (no change beyond repeatability) | Hypothesis 1 rejected: the routing does not cost amplitude. | Keep `d`. Go to step 4. Close #21 as "harmless to amplitude", and still record the mains share in both. |
| Anything else (one board only, or 1.2 × s < ρ < 1.5) | Partial or board-dependent. | Repeat step 1 once before deciding. Do not change the default. |
| Step 2: `measured/nominal` within 0.90–1.10 on both boards | The nominal scale holds (gain error ±2.5%, p.4; source ±2%, p.5; the low-pass's exact response at 16 Hz is not specified). | Close #23: amplitudes may be quoted in millivolts, labelled with the measured factor. |
| Step 2: outside 0.90–1.10 | Scale or gain is off by that factor. | Use the measured factor; read `CNFG_ECG` back and add it to the `# cfg` line. |
| Step 4: QRS ≥ 0.5 mV on the wide leads | Hypothesis 2: placement explains the rest. | Record placements with every capture from now on. |
| Step 4: still about 0.1 mV on a wide lead | None of 1–3. | Hypothesis 4: cable and clip continuity, then one board with gel electrodes. |

Step 3 is not a decision. It shows what open inputs do without the sources holding them:
expect `e` to be noisier or pinned, and note whether `raw_mean` and the `leadoff` column
change. That decides whether future electrode-free link tests need the inputs shorted.

**About the `c` prediction.** `bench_session_plan.md` says each edge is a 1.0 mV step of
about 2,621 codes, biased "a few percent" by the filters. The step size is right, but it
cannot be read off the waveform: at 16 Hz the 40 Hz low-pass removes most of the harmonics
and leaves something close to a sine, whose peak-to-peak is larger than the step.
`amplitude_check.py --cal` therefore takes the 16 Hz fundamental (exactly 16 samples per
period, both clocks derived from FCLK) and reports step = (π/2) × fundamental. On the
nominal scale the fundamental should be 1668.9 codes. The method was tested on a synthetic
square wave only; there is no `c` capture yet.

## Firmware: `e` as the power-up configuration (built, not the default)

```bash
INPUT_DEFAULT=e ./build.sh        # ring       -> build_e/
INPUT_DEFAULT=e ./build_ref.sh    # reference  -> build_ref_e/
INPUT_DEFAULT=e ./build_test.sh   # test board -> build_test_e/
INPUT_DEFAULT=e ./flash.sh /dev/ttyACM0     # ring; for the reference board use the esptool
                                            # command in CLAUDE.md with build_ref_e/src_build_ref_e.ino.*
```

This compiles the same `sketch.ino` with `-DINPUT_DEFAULT_E`. After `begin()` and before the
interrupt is armed, it applies the `e` values, and the boot log shows

```
# build: INPUT_DEFAULT_E - boots in 'e' (electrodes only, calibration sources off)
# cfg emux:000000 cal:000000 mode:e-default (set)
```

Nothing else differs, `d` still restores the `begin()` values, and the variants build into
their own directories so they cannot overwrite the default images. Without the variable the
build is unchanged and boards boot in `mode:begin`, as now.

**The A/B test does not need this build**; it uses the default image and the runtime
commands. The option exists so that, if the result favours `e`, a board that resets
mid-session does not fall back to `d`. Making `e` the default for every build is a one-line
change after that, on both boards at once.

One consequence to expect in `e`: with lead bias off, the only DC path for the inputs is the
third electrode, which the reference board wires straight to the VCM pin (R19, 0 Ω). With a
3-wire cable that is fine. With the cable unplugged or a 2-wire cable, the inputs float.

## Sources for the expected amplitudes

1. [Low QRS Voltage, LITFL ECG Library](https://litfl.com/low-qrs-voltage-ecg-library/)
2. [Low QRS voltage: why every ECG interpreter should know more about it](https://squigglylines.substack.com/p/low-qrs-voltage)
3. [Normal ECG, Queen's University](https://elentra.healthsci.queensu.ca/assets/modules/ECG/normal_ecg.html) and [a table of typical lead II features](https://pmc.ncbi.nlm.nih.gov/articles/PMC7152098/table/t0010)
4. [Bipolar-lead study, 36 patients (PubMed 24857184)](https://pubmed.ncbi.nlm.nih.gov/24857184)
5. [Puurtinen, *Precordial Bipolar Leads for Mobile ECG Applications*, thesis, 2012](https://trepo.tuni.fi/handle/10024/115171)

These were read as search summaries, not in full. Check the figures in the sources before
any of them goes into a report.
