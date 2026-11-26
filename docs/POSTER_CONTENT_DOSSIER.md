# Poster content dossier: BTP Phase I, finger-electrode ECG ring

Prepared 25 Nov 2026 from `main` at `dc30879` (tag `phase1-report-final` is the report's freeze).
This is an **audit plus content plan** for the Phase-I poster. It is not the poster.

**How to use this file (poster designer / Cowork):**

- Every number below comes from a saved file in `analysis/` or `captures/`, named beside it.
  A number marked *derived* was computed in this dossier from parameters or from saved numbers;
  the arithmetic is shown. **Do not add any number that is not in this file.** If a file and
  this page disagree, the file is right.
- Code labels: **[FW]** firmware (`sketch.ino`), **[Py]** Python reference implementation,
  **[Kt]** Android app (Kotlin). "Ported" means the Kotlin is pinned to the Python by a parity
  test. It does **not** mean the phone has run it live with a board. That has never happened.
- Data labels: **DEV** = used to set parameters. **HELD-OUT** = run once after the parameters
  were frozen in a commit, with nothing changed afterwards. **EXTERNAL** = a held-out run on a
  different database from the one developed on.
- Sections 10, 11 and 14 are what the designer needs most. Section 15 lists questions only
  the author can answer.

---

## 1. Title suggestions

1. **Timing the Beat, Not Just Finding It: Validated Acquisition and Polarity-Free Beat Timing
   for a Finger-Electrode ECG Ring** (recommended: it names the central finding)
2. When Real-Time Filtering Moves the Beat: Template-Alignment Beat Timing for Phone-Based
   Finger-ECG HRV
3. From FIFO to HRV: An Evidence-Gated Real-Time ECG Pipeline for a Finger-Electrode Ring
4. A Finger-Electrode ECG Ring: Validated Acquisition, Beat Timing and Physiological Analytics
   on a Wearable Platform (the Phase-I report's title; use it if the poster must match the report)

None of these claims novelty ("first", "novel"), and none should be edited to do so.

---

## 2. Abstract (about 210 words)

> Finger-electrode ECG rings report beat-to-beat measures computed in real time on a phone,
> where any error in the time given to each beat is amplified into heart-rate variability (HRV).
> We built an acquisition and analysis chain around the MAX30003 analogue front end. One
> firmware source runs on an ESP32-C3 ring-format board and on an ESP32 reference board. The
> front end's sample index, not a microcontroller or host clock, is the time base, and sample
> integrity is checked on the host. A streaming Pan–Tompkins detector, written sample by sample
> in Python and ported to Android under parity tests, reached sensitivity 99.78% and positive
> predictivity 99.32% on 32 MIT-BIH records held out from development (73,159 beats). The
> phone's causal filter makes the conventional timing point jump between QRS lobes: in a
> simultaneous finger and chest recording, 48 of 179 matched beats were displaced, and finger RMSSD read
> 36.7 ms against 18.3 ms at the chest. A template-alignment timing point (tp3) aligns each beat
> to a running median beat, interpolates to a fraction of a sample and makes no polarity
> decision. It brought the finger to 17.9 ms, narrowed the finger–chest RR limits of agreement
> from −37.6…+37.5 ms to ±1.8 ms, and on the held-out INCART database cut the patients with
> under 50% usable intervals from 11 to 2 of 32. HRV, breathing rate and quality are reported
> only inside enforced validity rules. The finger–chest comparison covers one subject at rest
> for 105 s.

Sources: `analysis/heldout_ec57_tp2.1.txt`, `analysis/fiducial_20260929_163314_dual03_both3wire_c3chest_wroomfinger_v2.txt`,
`analysis/tp3_own_recordings.txt`, `analysis/tp3_incart_heldout.txt`.

---

## 3. Problem statement and motivation

- A finger ECG (one electrode per hand, approximately limb lead I) is small and noisy. Heart
  rate survives that. Beat-to-beat measures (RMSSD, RR intervals, breathing from RSA, rhythm
  irregularity) do not, because they are **differences of differences of beat times**.
- Everything has to run **causally on a phone**. The filter delays and reshapes the QRS
  differently from the zero-phase (`filtfilt`) filter that offline studies use, so a result
  validated offline does not transfer automatically.
- Validation on public chest-lead databases does not show that a finger signal processed in
  real time behaves the same way. Commercial devices rarely publish the chain of evidence from
  electrode to number.
- **Research question:** can a finger ECG, acquired on low-cost hardware and processed causally
  on a phone, give beat timing good enough for HRV, and can the system *withhold* every number
  it cannot support?

---

## 4. Phase-I scope: planned, delivered, and not delivered

Phase I in the project plan (`docs/ECG_Ring_SoC_Project_Plan.docx`) is **ECG Ring development
and validation, September to November 2026**. Phase II (SoC test setup, mid-Nov 2026 to Feb
2027) is **not** part of this poster.

| Plan item (month) | Status on 25 Nov 2026 | Evidence |
|---|---|---|
| MCU board bring-up (Sep) | **Done** on two boards: ESP32-C3 SuperMini (ring format) and the custom ESP32-WROOM-32E reference PCB | `CLAUDE.md`, `docs/report/figs/ref_board.jpg` |
| Interrupt-driven 256 SPS firmware with timestamping and per-sample status (Sep) | **Done** [FW] | `sketch.ino` |
| Identical firmware on both boards (Sep) | **Done**: one source file; both boards flashed with the same build on 29 Sep | `CLAUDE.md` status |
| Wired and wireless path with packet-loss detection (Sep) | **Implemented.** USB has a host-verified integrity result. BLE has no saved integrity result with ECG, and **no live phone + board session has been run** | `analysis/integrity_20260929_152557_linktest_noelectrodes.txt`; `docs/phase1_results.md` §11 |
| Milestone: 5-minute capture, no data loss (Sep) | **Partly evidenced.** The host-verified link test is 174.61 s (3 min). A 5-minute capture from 19 Aug (60 counter lines × 5 s) ends with firmware counters `ovf:0 logdrop:0`, but no host-side integrity check of it is saved, and it is an older build | `analysis/integrity_...linktest...txt`; `captures/20260819_153726_gate_rest_01.log` |
| Dual-site recording protocol and first set (Sep) | **Done, minimal**: three dual captures on 29 Sep from one subject; one (dual03) is usable | `captures/20260929_*dual0*` |
| Finger–chest agreement: bias, LoA, ICC (Sep) | **Done** on dual03 | `analysis/agreement_..._dual03_..._ref_tp2.txt` |
| Ethics application (Sep) | **Unknown**: listed as an open question in `docs/MIDTERM_PLAN.md` | §15 |
| Flex PCB schematic, layout, fabrication (Oct) | **Not this author's work.** Designed by the lab's embedded hardware team; the report says fabricated, assembly under way; **not brought up**, and `sketch.ino` does not support it | `docs/report/main.tex` §III-C; `CLAUDE.md` board table |
| Filtering chain in the app with characterised delay (Oct) | **Done** [Kt] | `EcgFilter.kt` |
| Beat detection, RR and HRV on live data (Oct) | **Implemented and parity-tested, run on replayed recordings only** | `analysis/phase1_test_run.txt`, `analysis/app_phone_replay_tb02.txt` |
| Detector benchmark, Se and P+ on annotated data (Oct) | **Done**, held-out | `analysis/heldout_ec57_tp2.1.txt` |
| Signal-quality gate (Oct) | **Done** (sqi2); thresholds **not calibrated** on our hardware | `sqi_config.json` |
| Synchronised ECG + sensor storage (Oct) | **Not done**: sensor streams are in the firmware but **never flashed or run**; the app stores session reports, not sensor data | `CLAUDE.md` status (10 Nov) |
| Supervised patient data collection (Nov) | **Not done** | – |
| Thresholds refined on collected data (Nov) | **Not done** | – |
| Validation report (Nov) | **Done**: Phase-I report and `docs/phase1_results.md` | tag `phase1-report-final` |

**Work outside the plan, done in Phase I and in scope for the poster:** the tp3 timing point,
the validity-gated HRV suite, the artifact check in the quality gate, ECG-derived breathing,
ventricular ectopic labels, the AF screen and the WESAD arousal model (`docs/MIDTERM_PLAN.md`,
weeks 1–2).

**The plan deviation to state on the poster:** no ring-shaped device and no patient study
exist yet. Phase I therefore validates the platform on a reference board and a ring-format
development board, and validates the algorithms on public databases.

**Keep off the poster as results:** flex PCB (unless credited to the hardware team as Phase-II
hardware); PPG, GSR, temperature and IMU (no validated result); oscillator drift (not measured);
ECG amplitude in millivolts (scale unverified, signal about 10× low); any morphology claim
(electrodes recorded lead −II); SoC work.

---

## 5. Main technical contributions, ranked

Scores: H / M / L. "Evidence" means strength of the experimental support, not the amount of
code.

| Rank | Contribution | Novelty and depth | Phase-I relevance | Evidence | Visual potential | Recommendation |
|---|---|---|---|---|---|---|
| **1** | **Lobe-jumping under causal filtering, and the tp3 template-alignment timing point** [Py][Kt] | H: a mechanism found and explained by an error-propagation model, then a timing rule with no polarity decision | H: HRV on the phone depends on it | **H**: held-out INCART once; 48 MIT-BIH records (dev); dual03 (dev); port identical in 100 of 100 runs | **H**: bimodal histogram, correlation-lag diagram, before/after bars | **Centrepiece** (largest panel) |
| **2** | **Streaming Pan–Tompkins with robustness fixes and Python↔Kotlin parity** [Py][Kt] | M: classical core; the additions (search-back localisation fix, threshold stall-decay, lost-sample `skip()`) are the contribution | H: the plan's detection deliverable | **H**: held-out EC57, 73,159 beats, plus ablations | M: pipeline diagram and table | Major panel |
| **3** | **Firmware: the front end's sample index as the clock, integrity first** [FW] | M: careful register and FIFO work, measured design decisions | H: the plan's September deliverable | M: one host-verified link test (2 × ~44.5k samples), firmware counters, noise floor matches datasheet | **H**: data-flow / timing diagram | Major panel |
| **4** | **Finger vs chest on identical hardware** (dual03) | M | **H**: the plan's correlation-study deliverable | **L–M**: 1 subject, 105 s, seated; DEV data for tp3 | H: traces and Bland–Altman | Results panel, caveat in the same box |
| **5** | **Validity-gated HRV and the quality gate (sqi2)** [Py][Kt] | M: minimum windows, 95% coverage rule from simulation, a Nyquist-style HF rule, artifact check | M | M: arithmetic identical to neurokit2; gate on DEV data only | M | Supporting panel |
| **6** | **Analytics on public data**: breathing [Py][Kt], ventricular ectopic [Py], AF screen [Py], WESAD arousal [Py] | M | L–M: beyond the plan | M–H: held-out or external runs, but public data and mostly Python only | M | One compact table |

Not recommended as contributions: the flex PCB (another team's design), sensor firmware (never
run), the app UI (show as a screenshot strip at most).

---

## 6. Firmware architecture and acquisition [FW]

### 6.1 Hardware context

| | Ring-format board | Reference board |
|---|---|---|
| MCU | ESP32-C3 SuperMini, native USB-CDC | ESP32-WROOM-32E (8 MB) on a custom PCB, USB-UART bridge |
| MAX30003 SPI pins (CS / INTB / SYNC) | GPIO7 / GPIO10 / GPIO3 | IO5 / IO15 / IO25 (CS found by an SPI scan; the schematic label is wrong) |
| BLE | on (NimBLE) | off |
| Front-end clock | – (not documented for this board) | SiT1533 32.768 kHz oscillator (report §III-A) |

In dual03 the **ring-format board was on the chest** and the **reference board on the fingers**
(file names `..._c3chest_wroomfinger_ring.csv` / `_ref.csv`). The poster must say "board A /
board B" or state this explicitly, because "ring" here does not mean "finger".

### 6.2 MAX30003 configuration (checked against datasheet Rev 3, `docs/MAX30003_datasheet_check.md`)

| Register / setting | Value | Meaning | Source page |
|---|---|---|---|
| `CNFG_ECG` rate | 256 SPS via `setSamplingRate(SR_256)` | library `begin()` leaves 128 SPS; 256 halves RR quantisation from 7.8 to 3.9 ms (*derived*: 1/128 s, 1/256 s) | `sketch.ino` |
| Gain, on-chip filters | 20 V/V, 0.5 Hz high-pass, 40.96 Hz low-pass | from `begin()` | `CLAUDE.md` (decoded) |
| `EN_INT` | `0xC00001` | FIFO and overflow interrupts, **INTB push-pull** | p.28 |
| `MNGR_INT` | `0x180004` | EFIT = 3 → interrupt at **4** unread samples | p.29 |
| FIFO | 32 words × 24 bits | – | p.41 |
| FIFO word | `[23:6]` sample, `[5:3]` ETAG, `[2:0]` PTAG | decoded by our own `readEcgWord()` | p.41–42 |
| `CNFG_GEN` | `0x081007` (from `begin()`) | RBIAS off; DC lead-off on with 0 nA → the `leadoff` column is **not** a contact indicator | p.33–34 |
| `CNFG_EMUX` / `CNFG_CAL` | `0x0B0000` / `0x720000` (from `begin()`) | calibration sources routed onto the inputs with the electrodes connected: **open issue**, the leading suspect for the low amplitude | p.16, p.35 |

### 6.3 Acquisition data flow

```
MAX30003 (256 SPS, 32-word FIFO)
   │  INTB falls at 4 unread samples (every 15.625 ms, derived: 4/256 s)
   ▼
ISR (IRAM): record micros(), set flag. No SPI in the ISR.
   ▼
loop(): drain the FIFO completely (bounded at 64 reads)
   │  per word: decode 18-bit sample + ETAG
   │   ETAG 0/2 valid, 1/3 fast-recovery → index++, log, BLE batch
   │   ETAG 2/3 = last in FIFO → logged, then stop; ETAG 6 empty → stop
   │   ETAG 7 overflow → FIFO_RST, count ovf
   │  read STATUS (lead-off bits [3:0], clears latched bits)
   ├─► USB: "S,index,isr_micros,value,etag,leadoff"  (dropped, never blocked, when the TX buffer is short → host sees an index gap)
   └─► BLE notify (ring-format board): [seq:8][count=6][6 × 3-byte LE samples] = 20 bytes, one every 23.4 ms (derived: 6/256 s)
   ▼
Host (USB): capture.py → CSV → integrity.py (index continuity, gaps, duplicates, malformed rows)
Phone (BLE): seq gap g → detector.skip(6g); reconnection → breakStream(outage length by wall clock)
```

Safety net: a sweep runs if no interrupt has been serviced for 250 ms, so the FIFO cannot sit
undrained forever. It is gated on interrupt silence because an unconditional 100 ms sweep drained
the FIFO from under the interrupt (gaps of 6 sample periods instead of 4; `sketch.ino`
comment).

### 6.4 Engineering decisions worth poster space

| Decision | Why | Evidence |
|---|---|---|
| **Decode the FIFO word ourselves.** The ProtoCentral library's `readEcgSample()` returns the whole word sign-extended from bit 23 and never inspects ETAG | an overflowed FIFO then reads as plausible data. ECG captured before the fix (19 Aug 2026) is invalid: every sample carried the overflow flag | `sketch.ino`; `CLAUDE.md` rules |
| **Interrupt-driven drain** replacing a free-running `delay(8)` poll | the poll consumed slower than the sensor produced and silently overflowed the FIFO (after about 10 s, per the code comment) | firmware counters, 19 Aug, 5-minute capture: `ovf:0 logdrop:0 depth_max:5/32`, and interrupt gaps 15,618–19,533 µs in the last 5 s window (`captures/20260819_153726_gate_rest_01.log`; firmware-reported, older build) |
| **INTB push-pull, not open-drain** | with open-drain the ring board's interrupt line read low against the ESP32 pull-up: measured dead | `sketch.ino` comment; datasheet check |
| **The sample index is the clock**: sample N is at N/256 s on the front end's oscillator | MCU and host clocks are not trusted; RR intervals are index differences | host link test: rate by host clock 255.12 SPS whole capture vs 256.04 SPS middle 80%, which shows that host time is not a clock (`analysis/integrity_...linktest...txt`) |
| **Drop a log line rather than block** (`availableForWrite()` guard) | a blocked USB write stalls `loop()` long enough to overflow the FIFO. A dropped line shows up as an index gap the host can see | `sketch.ino` |
| **Judge integrity on the host, not from firmware counters** | an August reference capture lost 0.80% of samples on the serial link while the firmware reported `logdrop:0` | `CLAUDE.md` rules (capture `20260820_121738_ref_electrodes`) |
| **One source file for both boards**, pins selected at compile time | the finger–chest study only means something if decoding, registers, rate and timestamping are byte-identical | `sketch.ino` header |
| **BLE: 6 samples per 20-byte notification** | fits the default ATT payload with no MTU negotiation | `sketch.ino` |
| **BLE seq restarted at 0 on every subscribe** | seq free-ran while disconnected, so the phone counted every packet since boot as lost (the code comment records a reported 91.75% loss on a lossless link; no saved analysis file) | `sketch.ino` |
| **Phone keeps time across lost packets** (`skip(n)`) | feeding nothing would compress time: one lost packet would shorten an RR interval by 23.4 ms (*derived*: 6/256 s); the interval spanning the hole is dropped | `pan_tompkins.py` `skip()`, `EcgPipeline.kt` |

### 6.5 Measured acquisition quality

- **Host-verified link test** (29 Sep, no electrodes, both boards at once, 174.61 s): ring-format
  board 44,548 samples, reference board 44,545; **0 missing, 0 gaps, 0 duplicates, 0 backward
  jumps, 0 malformed rows** (`analysis/integrity_20260929_152557_linktest_noelectrodes.txt`).
- **Noise floor, no electrodes:** ring-format board **1.42 codes rms** against the datasheet's
  typical 0.53 µV rms = 1.39 codes on the nominal scale. The reference board reads 3.22 codes,
  69.8% of it mains (`analysis/amplitude_linktest_noelectrodes.txt`). The nominal scale
  (2621.44 codes/mV) is **unverified**, so quote codes, not µV.
- **Firmware counters** (19 Aug, 5-minute capture, older build): `ovf:0`, `logdrop:0`, deepest
  FIFO drain 5 of 32 words, interrupt gaps 15,618–19,533 µs in the last 5 s window against a
  nominal 15,625 µs (`captures/20260819_153726_gate_rest_01.log`). Firmware-reported only.

### 6.6 Firmware limitations (from code reading; state them if firmware is a headline)

1. **A FIFO overflow loses samples without an index gap.** The index advances only on drained
   samples, so "index = clock" holds only while `ovf` = 0, which only the firmware counter shows.
   Host index continuity catches serial loss, not FIFO loss. Both checks are needed.
2. **The BLE packet carries neither the sample index nor ETAG.** The 8-bit seq becomes ambiguous
   after 256 consecutive lost packets (6.0 s, *derived*: 256 × 23.4 ms). Fast-recovery samples
   are indistinguishable on the phone.
3. **The 250 ms safety sweep is longer than the FIFO's 125 ms of buffering** (*derived*:
   32/256 s). If the interrupt line died, the sweep would recover after an overflow rather
   than prevent it. This has not been observed.
4. **SYNC is implemented but was never wired.** No capture has a `K` line; alignment is by
   software from the beat trains.
5. **The current `sketch.ino` has not run on hardware.** The boards run the 29 Sep build. The
   sensor streams, the `d`/`e`/`c` input commands and the larger TX buffer are compiled, not
   flashed.

---

## 7. Algorithmic pipeline with equations

Pipeline order (phone and Python alike):

`raw codes → causal filter → 5–15 Hz band-pass → Pan–Tompkins detection → tp3 beat timing →
NN cleaning → validity-gated HRV / breathing → report`, with the quality gate running beside it
on the display signal.

Notation: $f_s = 256$ Hz, $T_s = 1/f_s = 3.906$ ms. Each equation lists its **status**:
*implemented* / *parity-tested* / *evaluated (data class)* / *theoretical*.

### E1. Sample decoding and time base [FW] *(poster: small, in the firmware panel)*

$$
s[N] = \operatorname{sext}_{18}\!\left(\left\lfloor w / 2^{6} \right\rfloor\right), \qquad
\mathrm{ETAG} = \left\lfloor w / 2^{3}\right\rfloor \bmod 8, \qquad
t_N = \frac{N}{f_s}
$$

- $w$: 24-bit FIFO word; $\operatorname{sext}_{18}$: sign extension from bit 17; $N$: sample
  index, incremented for each drained sample with ETAG ∈ {0, 1, 2, 3}.
- Why it matters: every later time (RR, beat time, HRV) is an index difference on the front
  end's oscillator, independent of MCU, USB, BLE or phone timing.
- Status: implemented; field layout checked against the datasheet (p.41–42); index continuity
  verified on the host in one link test.

### E2. Causal monitoring filter [Kt] (zero-phase equivalent offline [Py]) *(poster: one line)*

Cascade of RBJ-cookbook biquads (Direct Form II transposed):

$$
H(z)=\prod_{k}\frac{b_{0k}+b_{1k}z^{-1}+b_{2k}z^{-2}}{1+a_{1k}z^{-1}+a_{2k}z^{-2}}
$$

- High-pass 0.5 Hz, 4th-order Butterworth = two biquads with $Q_k = 1/(2\cos\theta_k)$,
  $\theta_k \in \{\pi/8, 3\pi/8\}$ → $Q = 0.5412, 1.3066$ (the values in `EcgFilter.kt`).
- Notches at 50 and 100 Hz, $Q = 30$ → −3 dB width $f_0/Q$ = 1.67 Hz and 3.33 Hz (*derived*).
- Low-pass 40 Hz, 4th-order Butterworth (same two Q values).
- **Delay: 2 samples (7.8 ms)**, measured by cross-correlating the causal output with the
  zero-phase output on a 14 s finger capture. The source is the `EcgFilter.kt` docstring; **no
  saved analysis file**, so quote it as "measured during development".
- Status: implemented [Kt]; this causal filter is what causes lobe-jumping (E4).

### E3. Streaming Pan–Tompkins detection [Py][Kt] *(poster: compact block)*

Band-pass 5–15 Hz (2nd-order high-pass at 5 Hz, then 2nd-order low-pass at 15 Hz, $Q = 0.7071$),
giving $y[n]$. Then

$$
d[n]=\tfrac18\bigl(2y[n]+y[n-1]-y[n-3]-2y[n-4]\bigr),\qquad
m[n]=\frac1W\sum_{k=0}^{W-1}d^{2}[n-k],\quad W=\lfloor 0.150 f_s\rfloor = 38
$$

For each local maximum $p$ of $m[n]$:

$$
\mathrm{THR}_1=\mathrm{NPK}+\tfrac14(\mathrm{SPK}-\mathrm{NPK}),\qquad
\mathrm{THR}_2=\tfrac12\,\mathrm{THR}_1
$$

$$
\text{beat: }\ \mathrm{SPK}\leftarrow 0.875\,\mathrm{SPK}+0.125\,p;\qquad
\text{noise: }\ \mathrm{NPK}\leftarrow 0.875\,\mathrm{NPK}+0.125\,p
$$

- Refractory 200 ms (51 samples). T-wave rule: a candidate within 360 ms of the last beat and
  below $0.5\,\mathrm{SPK}$ is noise. Warm-up 2 s.
- **Search-back:** with no beat for $1.66\,\overline{RR}$ (mean of the last 8 RR), the largest
  rejected candidate above $\mathrm{THR}_2$ becomes a beat, and
  $\mathrm{SPK}\leftarrow 0.75\,\mathrm{SPK}+0.25\,p$.
- **Contribution 1, search-back localisation fix (23 Oct):** a searched-back beat is located by
  the maximum $|y|$ over the 200 ms ending at **its own** integrator peak, not at the current
  sample, which can be up to 1.66 RR later and on a different beat. EC57, 12 development
  records: Se/P+ **98.50/97.31 → 99.52/98.32%** with positions at the 5–15 Hz peak
  (`analysis/ec57_benchmark.txt`, `analysis/ec57_benchmark_tp2.txt`).
- **Contribution 2, threshold stall-decay:** after 3 s with no beat, once per second
  $\mathrm{SPK}\leftarrow\max(\mathrm{NPK},\,\mathrm{SPK}/2)$. A transient far larger than any
  R wave (electrodes settling) otherwise leaves $\mathrm{THR}_1$ above every later beat for the
  rest of the recording; search-back cannot rescue it because no RR history is ever built. The
  decay is geometric, so recovery takes about $\log_2$ (transient ÷ beat size) seconds (*derived*).
- **Contribution 3, lost samples:** `skip(n)` advances the clock by $n$, fills the history with
  NaN (no window can read stale data), and drops the RR interval that spans the hole.
- Ablation (tp1, 12 dev records): without search-back Se falls from 98.49% to 94.86%, and on
  record 228 from 95.7% to 52.1% (`analysis/ablation_searchback_refine.txt`).
- Status: implemented in both languages, parity-tested, EC57 **HELD-OUT** (§9.2).

### E4. Why beat timing matters: error propagation into RMSSD *(poster: the key equation)*

Let the true beat times be $t_i$ and the measured times $\hat t_i = t_i + e_i$, with errors
independent of the rhythm, zero mean and variance $\sigma^2$. The successive RR difference is a
second difference of beat times, so

$$
\Delta\widehat{RR}_i=\Delta RR_i+\bigl(e_{i+2}-2e_{i+1}+e_i\bigr)
\;\;\Longrightarrow\;\;
\mathrm{RMSSD}^2_{\text{meas}}\;\approx\;\mathrm{RMSSD}^2_{\text{true}}+6\sigma^2
$$

The coefficients are $(1, -2, 1)$, so the variance is $(1+4+1)\sigma^2$.

| Error source | $\sigma$ | Effect on an 18 ms RMSSD |
|---|---|---|
| Quantisation at 256 Hz | $T_s/\sqrt{12}$ = 1.13 ms (*derived*) | $\sqrt{18^2+6\cdot1.13^2}-18\approx$ **+0.2 ms** (*derived*) |
| Lobe-jumping (bp timing point, causal filter, finger) | solve $36.7^2 = 18.3^2 + 6\sigma^2$ → **σ ≈ 13 ms** (*derived* from saved RMSSDs) | **×2** (measured: 36.7 vs 18.3 ms) |

- **Consistency check (*derived*):** a two-valued error that displaces a fraction $q$ of beats
  by $\Delta$ has $\sigma^2 = q(1-q)\Delta^2$. With $q = 48/179$ and $\Delta$ between 25 and
  35 ms (the displaced pairs span −39…+35 ms), $\sigma$ lies between 11.1 and 15.5 ms, which
  brackets the 13 ms above. The model is approximate: NN cleaning removes some displaced
  intervals, and the jumps may happen at either site.
- Sources: 36.7 ms (finger, bp, causal) from `analysis/fiducial_..._dual03_..._v2.txt`; 18.3 ms
  (chest, tp3, causal) from `analysis/tp3_own_recordings.txt`.
- Status: **theoretical model**, consistent with the measurement. This equation explains why
  heart rate was never affected while RMSSD doubled.

### E5. tp3: template-alignment beat timing [Py][Kt] *(poster: centrepiece math)*

**Parameters** (`tp2_config.json`, version tp3, frozen 13 Nov 2026):
$L_b = \lfloor 0.100 f_s\rfloor = 25$, $L_a = \lfloor 0.060 f_s\rfloor = 15$, window length
$L = L_b + L_a + 1 = 41$ samples; template depth $K = 16$ (`POL_KEEP`), ready at 8 (`POL_MIN`);
lag range $M = 10$ samples = 39 ms (`CORR_LAG`); $R_{\min} = 0.8$; peak tracking $\pm 2$
samples (`TRACK`).

1. **Anchor:** $d$ = the sample of maximum $|y|$ (5–15 Hz) in the 200 ms ending at the beat's
   integrator peak. This is the old timing point (tp1); tp3 only uses it as a starting point.
2. **Detrend** $D(\cdot)$: subtract the straight line through the mean of the first 3 and the
   mean of the last 3 samples of a window.
3. **Template (median beat):**
   $T[i] = D\bigl(\operatorname{median}_{j\in\text{last }K}\, s_j[i]\bigr)$, $i = 0..L-1$,
   where each stored window $s_j$ was cut at that beat's own best lag, which keeps the template
   sharp.
4. **Lag search**, for $\ell \in \{-M,\dots,M\}$, with
   $w_\ell[i] = D\bigl(x[d-L_b+\ell+i]\bigr)$:

$$
r(\ell)=\frac{\sum_{i}\bigl(w_\ell[i]-\bar w_\ell\bigr)\bigl(T[i]-\bar T\bigr)}
{\sqrt{\sum_i\bigl(w_\ell[i]-\bar w_\ell\bigr)^2\;\sum_i\bigl(T[i]-\bar T\bigr)^2}},
\qquad
\ell^\ast=\arg\max_\ell\, r(\ell)
$$

   The maximum is of the **signed** $r$. An inverted beat scores low and is flagged; it is not
   re-signed. That is why no polarity decision is needed.
5. **Sub-sample refinement** (parabola through the three correlations at the peak):

$$
\delta=\frac12\,\frac{r(\ell^\ast-1)-r(\ell^\ast+1)}{r(\ell^\ast-1)-2r(\ell^\ast)+r(\ell^\ast+1)},
\qquad |\delta|\le\tfrac12
$$

6. **Reference peak, followed and never chosen per beat:** $k_{\text{ref}}$ is the extremum of
   $T$ tracked from template to template within $\pm 2$ samples, with the same sign. If it is
   lost, it is re-picked as $\arg\max|T|$ and that beat is flagged. $\delta_k$ is its parabolic
   offset on $T$.
7. **Beat time** (fractional sample index):

$$
\hat t \;=\; d+\ell^\ast+\delta+\bigl(k_{\text{ref}}+\delta_k-L_b\bigr)
$$

8. **Flag** (time falls back to the 5–15 Hz peak; the beat is kept out of HRV) when the template
   holds fewer than 8 beats, the stretch $x[d-L_b-M \dots d+L_a+M]$ holds a gap, or
   $r(\ell^\ast) < 0.8$, or $\ell^\ast = \pm M$ (maximum at the edge of the range), or the
   reference peak was re-picked.
9. **Latency:** a beat is timed $L_a + M = 25$ samples (97.7 ms, *derived*) after its 5–15 Hz
   peak.

**Why each piece is there (evidence, all from saved files):**

| Design element | What goes wrong without it | Evidence |
|---|---|---|
| Alignment instead of a peak pick | causal filtering makes the 5–15 Hz maximum two-valued (lobe-jumping) | dual03 causal: 48 of 179 matched beats displaced, −39…+35 ms; zero-phase: 1 (`fiducial_..._v2.txt`) |
| No polarity decision | tp2.1 needed a lobe ratio ≥ 1.5 to choose a polarity; biphasic QRS under the causal filter has a median ratio of **1.15–1.22**, so every beat was flagged and **coverage was 0%** on MIT-BIH 111, 117, 215, 230 | `analysis/heldout_coverage_diagnosis.txt`; tp3 gives 97, 99, 82, 99% coverage on those records (`analysis/tp3_mitdb48_dev.txt`, causal) |
| Time referred to a **followed** template peak, not to the alignment alone | with alignment alone ("anchor"), absolute beat times random-walk against the annotations while RR stays right: sd against annotation **3.51 ms** against **1.10 ms** with the peak reference | `analysis/tp3_mitdb48_dev_grid.txt` (causal, 44 non-paced, lag 10, r 0.5 rows) |
| $R_{\min}$ = 0.8 and an interior-maximum rule | a beat unlike the template (ectopic, artifact) would otherwise be timed on a spurious alignment | design; grid in `tp3_mitdb48_dev_grid.txt` |

**Status:** implemented in Python and Kotlin. The Kotlin port is identical to the evaluated
candidate in **100 of 100 runs**, largest position difference **5.8 × 10⁻¹¹ samples**
(`analysis/tp3_port_check.txt`). Evaluated on **DEV** data (48 MIT-BIH records, dual03, tb01,
tb02) and **HELD-OUT once** on INCART (§9.4).

**Known limits** (state them in the panel):

- A 5–15 Hz peak that alternates between places more than 39 ms apart has no interior
  correlation maximum. On INCART patient 24 coverage on one record fell from 90% to 48%
  (`analysis/tp3_diagnosis_incart_patient24.txt`). Found on held-out data, so not changed.
- After a real polarity flip the followed peak can settle on another lobe. Beats are then
  timed at a constant offset (+21.6 ms, sd 0.61 ms, in the `polarity_flip` fixture: a real
  finger recording inverted at 30 s).
  RR is unaffected (RMSSD 22.29 vs 22.53 ms unflipped) (`analysis/parity_fixtures_tp3.txt`).
- RMSSD reads slightly low against annotations (median −0.15 ms on MIT-BIH, causal).

### E6. NN cleaning and coverage [Py][Kt] *(poster: one box)*

- An interval is **usable** when both of its beats are primary detections (not search-back),
  unflagged, and no samples were lost between them. **Valid** means 300 ≤ RR ≤ 2000 ms.
- Accept $RR_i$ iff $|RR_i-\rho|\le 0.2\,\rho$, then set $\rho \leftarrow RR_i$. The seed
  $\rho_0$ is the median of the first 5 valid intervals. After 5 consecutive rejections,
  $\rho \leftarrow$ their median, so a real step change in rate cannot lock the series out.

$$
\mathrm{RMSSD}=\sqrt{\frac{1}{|P|}\sum_{(i,i+1)\in P}\bigl(RR_{i+1}-RR_i\bigr)^2},
\qquad
c=\frac{\#\,\text{accepted NN}}{\#\,\text{inter-beat intervals}}
$$

- $P$: pairs of **adjacent** accepted intervals. Nothing is differenced across a hole.
- $c$ (coverage) is reported beside every HRV value (project rule). One flagged beat removes two
  intervals, so for a flag rate $p$, $c \approx 1-2p$. The simulation shows it: 5% flagged gave
  90.1% coverage (`analysis/hrv_min_window_simulation.txt`).
- Status: implemented in both languages, parity-tested to 1e-9 on four real-recording cases.

### E7. Frequency-domain HRV without interpolation, with validity rules [Py][Kt] *(poster: optional)*

Lomb–Scargle periodogram of the mean-removed NN series $y_j$ at beat times $t_j$:

$$
P(\omega)=\frac12\left[\frac{\bigl(\sum_j y_j\cos\omega(t_j-\tau)\bigr)^2}{\sum_j\cos^2\omega(t_j-\tau)}
+\frac{\bigl(\sum_j y_j\sin\omega(t_j-\tau)\bigr)^2}{\sum_j\sin^2\omega(t_j-\tau)}\right],
\qquad \tan 2\omega\tau=\frac{\sum_j\sin2\omega t_j}{\sum_j\cos2\omega t_j}
$$

PSD $=2P\,T/N$ (ms²/Hz). LF $=\int_{0.04}^{0.15}$, HF $=\int_{0.15}^{0.40}$ by trapezoid on a
grid of step $\le 1/(8T)$.

- **HF needs beats fast enough to sample it:** withheld when the mean NN exceeds 1250 ms, that
  is, when the beat rate is below 2 × 0.40 Hz.
- **Holes bias band power upward.** In simulation, HF read **+15.9%** and **+30.3%** high at
  about 90% coverage (two synthetic series). Hence LF and HF are withheld below **95%**
  coverage (`analysis/hrv_min_window_simulation.txt`, part 2; **synthetic data**).
- LF/HF is shown only beside LF and HF and is not called "sympatho-vagal balance" (Billman 2013).
- Minimum windows (`algorithms/config.json`): RMSSD, pNN50, SD1 need 60 s and 30 intervals;
  SDNN, SD2 need 120 s; HF 60 s at ≥ 95% coverage; LF, LF/HF 120 s at ≥ 95%; DFA α1 120 s and
  200 intervals in runs (boxes 4–16, Peng 1995); sample entropy 180 s and 200 templates
  ($m=2$, $r=0.2\,$SD).
- Status: implemented in both languages; **arithmetic verified** against neurokit2 (§9.5). This
  checks arithmetic, not physiology.

### E8. Signal-quality gate sqi2 [Py][Kt] *(poster: one box with a small timeline)*

Over the last 5 s of the display signal $x$ and its 5–15 Hz version $q$:

$$
\mathrm{kSQI}=\frac{m_4}{m_2^{2}}\ \ (\text{Gaussian}=3),\qquad
\mathrm{pSQI}=\frac{\sum q^2}{\sum x^2}
$$

GOOD: kSQI ≥ 5 and pSQI ≥ 0.10. FAIR: kSQI ≥ 3.5 and pSQI ≥ 0.05. Otherwise POOR. These are
published-convention thresholds, **not calibrated on our hardware**.

**Artifact check (new in sqi2).** For consecutive 1 s blocks $b$:

$$
S_b=\max_{b}x-\min_{b}x,\qquad R_b=\operatorname{median}\{S_{b-29},\dots,S_b\},\qquad
\text{artifact}\iff S_b>4R_b \;\Rightarrow\;\text{POOR for 10 blocks}
$$

- Why: kurtosis rewards spikes, so an electrode-settling transient many times the size of a beat
  scores GOOD on kSQI and pSQI alone. tb02's swing reached 3366 against a reference of 108 in
  its first seconds (`analysis/sqi_artifact_dev.txt`, per-second listing).
- **Why the median and not a lower percentile:** at the same ratio and hold, a 25th-percentile
  reference turned **0.99%** of the old-GOOD MIT-BIH seconds to POOR; the median turned **0 of
  69,088** (`analysis/sqi_artifact_dev.txt`, grid rows `30 25 4 10` and `30 50 4 10`). At
  45 beats/min a quarter of the seconds hold no QRS, so a 25th-percentile reference would be the
  swing of a beat-free second and every beat would look like an artifact. The price is that the check goes blind
  when more than half of the last 30 s is artifact.
- Heart rate is displayed only on GOOD [Kt].
- Status: implemented in both languages, parity-tested; evaluated on **DEV data only**.

### Equations deliberately left off the poster

Bland–Altman, ICC(2,1), Lin's CCC, Se and P+ are standard; define them in one line in the
methods box. SD1/SD2, DFA α1, sample entropy and the coefficient of sample entropy are
implemented and arithmetic-checked, but they are background, not contributions. The breathing
fusion rule and the AF features belong in the analytics table's footnotes if anywhere.

---

## 8. Experimental methodology

### 8.1 Protocol discipline (show as a strip or footnote; reviewers notice it)

1. Develop and tune on DEV data.
2. Freeze the parameters in a version-controlled commit.
3. Run once on held-out or external data.
4. Change nothing in response.

The project rule is to split by patient or subject, never by beat.

| Frozen artefact | Commit / date | Held-out run |
|---|---|---|
| Detector tp2.1 | `da603e2`, 31 Oct | 36 MIT-BIH records, 31 Oct (`heldout_ec57_tp2.1.txt` confirms the frozen files were unchanged) |
| HRV / breathing alg1 | `467881d`, 11 Nov | BIDMC held-out subjects; MIT-BIH held-out (HRV arithmetic) |
| tp3 candidate | `17128f3`, 13 Nov | INCART, 13 Nov |
| Ectopic | frozen 13 Nov; DS2 run at `dd1029d` | MIT-BIH DS2 (not truly held out, §9.7) |
| AF af1 | frozen 13 Nov; run at `08d5bd9` | MIT-BIH AF Database |
| WESAD plan | `300b751`, 16 Nov; evaluation `fb1fa5c` | leave-one-subject-out, run once 23 Nov |

### 8.2 Data

| Dataset | Use | Size | Class |
|---|---|---|---|
| MIT-BIH Arrhythmia | EC57 detection; timing vs annotations | 48 records; 32 non-paced + 4 paced held out until 13 Nov | 12 DEV + 36 HELD-OUT (once, 31 Oct); all DEV since 13 Nov |
| St Petersburg INCART | tp3 timing | 75 records, 32 patients, lead II | HELD-OUT once (13 Nov); annotations algorithmic |
| BIDMC | breathing rate | 53 recordings, 46 subjects, split 23 / 23 by subject | DEV / HELD-OUT once |
| PhysioNet/CinC 2017 | AF development | 8,528 recordings, CV by recording | DEV |
| MIT-BIH AF Database | AF test | 23 patients, 28,104 windows of 30 s | EXTERNAL once |
| MIT-BIH Noise Stress Test | quality-gate harm check | 12 records | DEV |
| WESAD | arousal | 15 subjects | DEV for the feature code, LOSO for the classifier |
| Own: dual01–03 | finger vs chest | 29 Sep, one subject, seated; dual03 the usable one (105.6 s clean) | DEV (tp3 tuning used dual03) |
| Own: tb01, tb02 | session / timing coverage | 27 Oct, test board, 228 s / 299 s | DEV |
| Own: link test | acquisition integrity | 29 Sep, 174.61 s, no electrodes | – |

Settings common to the benchmarks: resampled to 256 Hz; MLII where present; 150 ms matching
tolerance; 60 Hz notch for US data, 50 Hz for ours; every result given for both the **causal**
(phone) and **zero-phase** (offline best-case) filter where it matters.

### 8.3 Dual-site protocol (dual03)

- Two boards running identical firmware, recording at the same time: board A (ESP32-C3) on the
  chest, board B (WROOM) on the fingers, one finger of each hand plus a reference clip. Both
  sites used a 3-wire cable.
- Seated, at rest, hands still. The first 10 s are skipped as settling.
- **Integrity checked first:** both channels 27,046 samples, 0 missing, 0 gaps, 0 duplicates
  (`agreement_..._dual03_..._ref_tp2.txt`).
- **Alignment in software** (the boards share no clock and SYNC was not wired): offset −17 ms
  from the beat trains. This is host serial latency, not physiology.
- Matching within 150 ms. Heart rate compared over 10 s windows (Bland–Altman, ICC(2,1), Lin's
  CCC). RR compared on consecutive matched beats where neither beat is flagged at either site.
- **Caveats:**
  - Heart-rate agreement rests on about **10 windows**. The saved plot shows 10 points; the
    saved summary does not print the count.
  - The heart rate during the recording was about 98–109 bpm (from the saved plot).
  - Electrode polarity was reversed (lead −II), which does not affect timing.

### 8.4 Software verification (not validation)

- Parity tests: phone and Python must agree on real-recording fixtures to 1e-9 (positions,
  flags, RMSSD, coverage), on four cases: chest, finger, artifact + lost packets, and polarity
  inverted mid-recording.
- Test run at the report freeze: Python **117 passed** (`tests/`) and 4 of 4
  (`test_capture_sensors.py`); Android **156 tests, 0 failures, 6 skipped** (screenshot tests
  that need an uncommitted replay asset) (`analysis/phase1_test_run.txt`).
- Passing tests show that the phone computes what the Python computes. They are not evidence that
  either is physiologically right; that is what §9 is for.

---

## 9. Verified quantitative results

### 9.1 Acquisition (own hardware)

| Measure | Result | Data | Source |
|---|---|---|---|
| Host-side index integrity, both boards, no electrodes | 44,548 + 44,545 samples; 0 missing, 0 gaps, 0 duplicates, 0 backward, 0 malformed | 174.61 s, 29 Sep | `analysis/integrity_20260929_152557_linktest_noelectrodes.txt` |
| Noise floor, ring-format board, no electrodes | 1.42 codes rms (datasheet typical = 1.39 codes on the unverified nominal scale) | 164 s analysed | `analysis/amplitude_linktest_noelectrodes.txt` |
| Firmware counters, 5-minute capture | ovf 0, logdrop 0, deepest drain 5/32, interrupt gap 15,618–19,533 µs (last 5 s window) | 19 Aug, older build, firmware-reported | `captures/20260819_153726_gate_rest_01.log` |
| Interrupt spacing, link test, both boards | median 15,625 µs (nominal 4/256 s); 1st–99th percentile 15,624–15,626 µs (ring-format) and 15,623–15,627 µs (reference), on the ESP32's clock | 174.6 s, 29 Sep | `analysis/poster_checks.txt` |
| QRS-to-noise, dual03 median beat | chest 19, finger 16 (QRS 270 and 100 codes) | 105.6 s | `analysis/amplitude_dual03.txt` |

### 9.2 Beat detection, ANSI/AAMI EC57, MIT-BIH, 256 Hz, 150 ms

| Detector | Records | Class | Beats | Se % | P+ % | Rejected |
|---|---|---|---|---|---|---|
| Initial (tp1) | 12 | DEV | – | 98.50 | 97.31 | – |
| NeuroKit2 (360 Hz, comparison) | 12 | DEV | – | 98.90 | 99.25 | – |
| Search-back fix, 5–15 Hz positions | 12 | DEV | – | 99.52 | 98.32 | – |
| Final, tp3 | 12 | DEV | – | 99.49 | 98.29 | – |
| **Final, tp2.1 detector, ungated** | **32 non-paced** | **HELD-OUT** | **73,159** | **99.78** | **99.32** | – |
| Same, bSQI ≥ 0.9 gate | 32 non-paced | HELD-OUT | – | 99.82 | 99.89 | 2.4% of recording time |
| Same, paced records (102, 104, 107, 217) | 4 | HELD-OUT | 8,761 | 99.55 | 99.24 | – |

- Sources: `analysis/ec57_benchmark.txt`, `ec57_benchmark_tp2.txt`, `ec57_benchmark_tp3.txt`,
  `heldout_ec57_tp2.1.txt`.
- Held-out totals: TP 72,997, FP 501, FN 162. **439 of the 501 false positives are record 207**
  (P+ 80.88%), which contains ventricular flutter that this benchmark scores and EC57 practice
  may exclude. Nothing was changed.
- tp3 changes only timing, not detection: on the same 36 records tp2.1 gives 99.75/99.31 and
  tp3 99.76/99.31 (`ec57_benchmark_tp3.txt`). That is **not** a held-out result, since the 36
  were spent by then.
- The ungated development P+ fails a 99% bar because of record 108 (P+ 83.52%).

### 9.3 Finger vs chest, same person, same time (dual03, 29 Sep)

| Measure | Result | Timing point | Source |
|---|---|---|---|
| Beat matching | 179 beats per site; Se 99.44%, P+ 99.44% (178 matched, 1 missed, 1 extra) | tp2 | `agreement_..._dual03_..._ref_tp2.txt` |
| HR bias, LoA | +0.03 bpm, −0.10 to +0.15 bpm (about 10 × 10 s windows) | tp2 | same |
| ICC(2,1), CCC | 0.9998, 0.9997 (on the same ~10 windows; HR range ~98–109 bpm) | tp2 | same |
| RR bias, LoA | +0.00 ms, −1.57 to +1.58 ms, n = 169 (8 flagged out) | tp2 | same |
| **RR LoA, causal (phone) filter** | **−1.8 to +1.8 ms, n = 166** | **tp3** | `tp3_own_recordings.txt` |
| **RMSSD, causal** | **chest 18.3 ms (coverage 92%), finger 17.9 ms (94%)** | **tp3** | same |
| RMSSD, zero-phase | chest 18.0 ms (94%), finger 17.9 ms (94%) | tp3 | same |

**Where the 166 comes from** (`analysis/poster_checks.txt`): 180 matched beats give 179 consecutive
intervals; 13 are left out because one of their four beats was flagged by the timing step at either
site. The 20% NN rule is **not** applied to these intervals. It belongs to the RMSSD: the finger keeps
168 of 179 intervals (93.9%), 2 dropped by the 20% rule and 9 next to a flagged beat.

**Caveat to print next to the table:** one subject, seated, 105 s. This is a feasibility
result, not a validation study, and the recording is development data for tp3. Do **not**
quote the drift estimate printed in the same file (−16.7 ± 7.3 ppm): at this length the fit has
no power, and its sign flipped when one setting changed.

### 9.4 Beat timing: lobe-jumping and tp3

**(a) The effect (dual03, finger vs chest, causal filter)**
(`analysis/fiducial_..._dual03_..._v2.txt` and `tp3_own_recordings.txt`)

| Timing point | Displaced pairs (>20 ms) | finger−chest RR LoA | Finger RMSSD | Chest RMSSD |
|---|---|---|---|---|
| 5–15 Hz peak (tp1, "bp"), zero-phase | 1 of 179 | −8.5…+8.5 ms | 18.6 ms | 17.9 ms |
| **5–15 Hz peak (tp1), causal** | **48 of 179** (−39…+35 ms) | **−37.6…+37.5 ms** | **36.7 ms** | 23.2 ms |
| **tp3, causal** | – (finger−chest dt sd 0.88 ms) | **−1.8…+1.8 ms** (n 166) | **17.9 ms** (94%) | 18.3 ms (92%) |

**(b) HELD-OUT: INCART, 75 records from 32 patients, run once, causal filter**
(`analysis/tp3_incart_heldout.txt`)

| | tp2.1 | tp3 |
|---|---|---|
| Median coverage (beats whose interval is used, ÷ annotated beats) | 56% | **68%** |
| Patients with pipeline NN coverage < 50% | 11 of 32 | **2 of 32** |
| Records with RMSSD withheld | 9 | **3** |
| RMSSD error vs annotations, median [range], per record | −0.50 [−32.92, +18.21] ms | **−0.69 [−8.80, +0.87] ms** |
| Mean absolute RMSSD error | 2.08 ms | **1.22 ms** |
| Per-patient RMSSD error, median [range] | −0.47 [−32.92, +8.82] ms | −0.76 [−6.46, −0.01] ms |
| Detection Se / P+ | 99.76 / 98.81% | 99.77 / 98.82% |

Zero-phase: coverage 55 → 68%, mean absolute error 2.68 → 1.19 ms. **INCART's beat positions
were placed by an algorithm**, so these errors compare the two timing points and do not
measure absolute accuracy. One regression: patient 24 (one record 90% → 48%).

**(c) DEV: MIT-BIH, 44 non-paced records, causal** (`analysis/tp3_mitdb48_dev.txt`)

| | tp2.1 | tp3 |
|---|---|---|
| Median coverage | 57% | **82%** |
| Records with RMSSD withheld | 5 | 1 |
| RMSSD error, median [range] | −0.03 [−2.46, +0.91] ms | −0.15 [−2.27, +3.45] ms |
| Mean absolute RMSSD error | 0.33 ms | 0.37 ms |
| Coverage on 111 / 117 / 215 / 230 | 0 / 0 / 0 / 0% | 97 / 99 / 82 / 99% |

**This is the honest trade:** tp3 makes far more beats usable and keeps the error small, but on
development data its error is not lower than tp2.1's where tp2.1 reported a value.

**(d) Own recordings, causal:** tb02 NN coverage 62.1% → **82.3%**; tb01 65.9% → 78.6%
(`tp3_own_recordings.txt`). These are test-board recordings with host-side losses (tb01: 232
samples lost in 30 gaps).

### 9.5 HRV implementation vs neurokit2 (arithmetic check, HELD-OUT MIT-BIH, tp2.1 beats)

(`analysis/hrv_vs_neurokit_mitdb_heldout.txt`; 192 windows of 300 s, 15 without holes)

| Measure | Windows reported (our minimums) | Difference from neurokit2 |
|---|---|---|
| RMSSD, SD1 | 182 / 192 | 0 on every window |
| SDNN, SD2 | 178 / 192 | 0 on every window |
| LF/HF | 67 / 192 (95% coverage rule) | ≤ 3.2% without holes, ≤ 4.7% with holes; ≤ 0.03% / 0.15% on neurokit2's own grid |
| DFA α1 (boxes 4–16) | 116 / 192 | ≤ 1.8e-15 on the 15 windows without holes |
| Sample entropy | 127 / 192 | ≤ 4.4e-16 on the 15 windows without holes |

This verifies arithmetic only; both sides received the same NN series.

### 9.6 Quality gate sqi2 (DEV data only)

| Data | Old-GOOD blocks turned to POOR by the artifact check | Source |
|---|---|---|
| tb02, first 42 s (electrode settling) | 19 of 20 (95.00%) | `analysis/sqi_artifact_dev.txt` |
| tb02 after 45 s; dual03 | 0 of 240; 0 of 177 | same |
| MIT-BIH, 48 records | **0 of 69,088** | same |
| Noise Stress Test, clean segments | **0 of 11,440** | same |

Through the app's own pipeline, tb02's first 42 s go from GOOD 47.8% to **2.5%** of verdicts
(`analysis/app_quality_gate_replay.txt`). Caveats: this rests on one settling episode and one
burst. dual03's finger channel is GOOD only 57.3% of the time (kSQI near its threshold).

### 9.7 Analytics on public data (compact table; all [Py], breathing also [Kt])

| Analysis | Test data | Result | Coverage / rejection | Class | Source |
|---|---|---|---|---|---|
| Breathing rate (fused RSA + R amplitude, causal) | BIDMC, 23 subjects, 3,141 reference windows | MAE 0.50 br/min, bias +0.17, LoA −2.9 to +3.3 | reported in **41%** of windows; per-subject median 16% | HELD-OUT | `breathing_bidmc_heldout.txt` |
| Ventricular ectopic (class V, causal) | MIT-BIH DS2, 22 records | Se 88.36%, P+ 82.67% | 98.6% of beats judged; end-to-end Se 86.06% | **not truly held out** (detector developed on all MIT-BIH) | `ectopic_mitdb_ds2.txt` |
| AF screen (30 s windows) | MIT-BIH AF Database, 23 patients, 28,104 windows | Se 92.22%, Sp 96.80% | 97.16% of windows decided; end-to-end Se 86.72% | EXTERNAL | `af_afdb_external.txt` |
| Arousal (stress vs rest), wrist only | WESAD, 15 subjects, LOSO | balanced accuracy 93.3% [84.2, 99.3] | 13.1% of stress / 5.2% of baseline windows rejected | DEV (feature code) | `wesad_evaluation.txt` |

Footnotes for this table:

- The AF screen is a **screening label, not a diagnosis**. It reads beat timing only, never P
  waves. Flutter is mostly missed (40 of 185 windows labelled A). P+ (94.79%) holds only at
  this database's 40% AF share.
- The S (supraventricular) label has P+ 23.3% and must not be shown.
- WESAD: no claim about psychological stress. The order confound means the ECG model called
  42.9% of amusement windows stress in the stress-first subjects, against 0.0% in the
  amusement-first ones. The signals come from WESAD's devices, not our boards.
- Breathing: no slow-breathing (6/min) data in the held-out set. RSA alone has MAE 5.35 br/min,
  so it is never reported by itself.

### 9.8 Phone app (replay only)

- The live heart rate was never more than 5 bpm from an independent NeuroKit2 reference at any
  of **1,359** displayed moments (dual03 444, tb02 915). The old display failed at 63 and 37
  (`analysis/app_live_hr.txt`).
- On the phone (SM-A566E), replaying tb02, the session report matched the JVM pipeline exactly
  (`analysis/app_phone_replay_tb02.txt`). That was a debug build from before the tp3 port.

---

## 10. Recommended poster figures

### 10.1 The 4–6 major visual elements (recommended set)

| # | Element | Built from | Status |
|---|---|---|---|
| **V1** | **System and acquisition data-flow diagram**: electrodes → MAX30003 (FIFO, ETAG) → ISR/drain → index → USB / BLE (6-sample packets, seq) → phone (skip, filter, detector, tp3, gate) → report; Python reference beside it, joined by "parity tests, 1e-9" | §6.3 and the report's Fig. 1 (TikZ in `docs/report/main.tex`) | **New drawing.** Facts are all in §6 |
| **V2** | **Lobe-jumping**: finger−chest beat-time histograms, causal filter, 5–15 Hz peak (bimodal) against tp3 (one narrow peak), with a 4 s trace inset | existing `docs/report/figs/fiducial_v2.png` (crop to two panels: "causal \| bp" and "causal \| R+parab+guard") plus `analysis/fiducial_20260929_163314_dual03_both3wire_c3chest_wroomfinger_v3_zoom_35.5-39.5s.png` | Existing, **but neither shows tp3**. See N3 for the true before/after |
| **V3** | **tp3 mechanism**: one real finger beat window, the 16-beat median template with the followed peak marked, the $r(\ell)$ curve over ±10 lags with the parabolic vertex, and the time equation $\hat t = d+\ell^\ast+\delta+(k_{\text{ref}}+\delta_k-L_b)$ | **N2** (new, from dual03) | New plot |
| **V4** | **What tp3 buys**: (a) finger RMSSD bars, 5–15 Hz peak vs tp3, chest line; (b) INCART per-patient coverage, tp2.1 → tp3 (dumbbell chart, patient 24 highlighted) | (a) existing `docs/report/figs/rmssd_timing_fix.pdf`; (b) **N4** (new) | (a) ready; (b) new |
| **V5** | **Validation table**: EC57 held-out, finger–chest, INCART, BIDMC, AFDB, each with its data class (DEV / HELD-OUT / EXTERNAL) and coverage | §9 tables | Typeset, no plot needed |
| **V6** *(optional)* | **Quality gate**: tb02 first 50 s, swing ÷ reference per second with the 4× line, old verdict vs new verdict | **N6** (new) | New plot |

### 10.2 Existing figures: assessment

| File | Shows | Poster use |
|---|---|---|
| `docs/report/figs/fiducial_v2.png` | 10 histograms: finger−chest dt for 5 timing points × 2 filters | **Yes, cropped.** Too dense as is. Predates tp3 |
| `analysis/fiducial_..._v3_zoom_35.5-39.5s.png` | 4 s of chest and finger traces, both filters, with bp / R+parab / tp2.1 markers | Yes, as an inset: the bp markers visibly miss the R peak under the causal filter |
| `docs/report/figs/rmssd_timing_fix.pdf` | finger RMSSD bp vs tp3, chest line, coverage under bars | **Yes, as is** (drawn by `docs/report/make_figures.py` from the saved files) |
| `docs/report/figs/agreement_dual03.png` | 10 s of both traces; HR Bland–Altman; identity plot | Top panel only. The Bland–Altman has about 10 points; prefer N8 (RR, n 166) |
| `docs/report/figs/ref_board.jpg`, `schematic-1.png` | reference board photo and schematic | Photo yes (small). Schematic too dense for a poster |
| `docs/report/figs/app_monitor.png`, `app_report.png`, `app_breathing.png`, `app_history.png` | app screens (replay) | A 4-phone strip; caption "replay of a recorded file" |
| `analysis/app_live_hr_tb02_beats.png` | live HR vs independent reference | Optional |
| `docs/report/figs/wesad_balacc.pdf` | WESAD balanced accuracy with intervals | Only if WESAD gets space |
| `docs/report/figs/flex_render.jpg` | flex PCB render | Only as "Phase II hardware", **credited to the lab's hardware team** |
| `analysis/qrs_polarity_dual03.png` | average beat, all deflections negative | Limitations box only (lead −II) |
| `analysis/slides/*.png` | September slides | **Do not use**: tp1-era figures, superseded |

### 10.3 New plots that can be generated from existing data (no new experiment)

All read-only on `captures/` and `analysis/`. None has been made yet.

| ID | Plot | Data | How |
|---|---|---|---|
| **N2** | tp3 mechanism on a real beat | `captures/20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv` (finger) | Run the causal chain and `pan_tompkins.PanTompkins` (tp3); copy `_locate_tp3`'s logic into a plotting script, or subclass it, to capture `full`, `t`, `r`, `kb`, `ref_k` for one unflagged beat. Do not edit `pan_tompkins.py` |
| **N3** | finger−chest dt histogram, causal, bp vs tp3 | dual03 both CSVs | `evaluate_tp3.py own` computes dt but saves only its sd (0.88 ms); export the per-beat arrays in a separate script |
| **N4** | INCART per-patient coverage tp2.1 → tp3 | the per-record table in `analysis/tp3_incart_heldout.txt` | Parse; average records per patient as the file's summary does; mark the 50% line and patient 24 |
| **N5** | Coverage vs HF/LF bias (why 95%) | table in `analysis/hrv_min_window_simulation.txt`, part 2 | Plot directly; label **"simulation, synthetic series"** |
| **N6** | tb02 artifact timeline | per-second `swing/reference, verdict` listing in `analysis/sqi_artifact_dev.txt` | Parse the first 50 s; horizontal line at 4× |
| **N7** | Validation "ladder" | §9 | Typeset graphic: dataset × class × headline result |
| **N8** | RR Bland–Altman, finger vs chest, tp3, causal | dual03 | Re-run the matching from `fiducial.py dual` / `evaluate_tp3.py own` with a per-pair export |

Any new figure must carry its data source and data class in the caption.

---

## 11. Suggested poster section hierarchy

Three columns (A0 portrait or landscape). Approximate share of area in brackets.

**Header:** title, author, supervisor, department and institute (logos in `docs/report/figs/`).

**Column 1: problem and platform (30%)**

1. **Motivation** (5%): three bullets from §3. The one-line hook is the error-propagation
   equation E4 in words: "beat-time errors enter RMSSD six times over".
2. **System architecture** (10%): V1. One sentence: "one firmware, two boards, the only
   difference is the electrode site".
3. **Firmware: the sample index is the clock** (15%): E1, the register table (trimmed to 4
   rows), 3–4 decisions from §6.4 (FIFO decoding, interrupt drain, drop-not-block, host-side
   integrity), the link-test result and the board photo.

**Column 2: the algorithm (40%)**

4. **Real-time pipeline** (8%): E2/E3 as a compact block diagram with parameters; E6 in one
   line; the three detector fixes.
5. **The finding: lobe-jumping** (12%): V2 and E4 with the 36.7 vs 18.3 ms numbers.
6. **tp3: template-alignment timing** (20%): V3 and E5 (steps 3–7 and the flag rule). The
   "why each piece" table trimmed to three rows. Port identical to 5.8e-11 samples.

**Column 3: evidence (30%)**

7. **Validation results** (18%): V4 and V5. Detection 99.78 / 99.32% held-out; INCART 11 → 2;
   dual03 RR ±1.8 ms with its caveat; HRV arithmetic = neurokit2.
8. **Validity and quality rules** (5%): minimum-window table (compact), 95% coverage rule, the
   sqi2 one-liner or V6.
9. **Beyond Phase I plan** (optional, 3%): the analytics table §9.7, four rows, with
   footnotes.
10. **Limitations and next steps** (4%): §12, five bullets.

**Footer:** key references (6–8) and the repository tag `phase1-report-final`.

Words: keep body text to about 600–800 words in total. Every number on the poster needs its
data class (DEV / HELD-OUT / EXTERNAL) and, for HRV, its coverage.

---

## 12. Limitations and future work

**Limitations (in priority order for the poster):**

1. **Finger vs chest is one subject, seated, 105 s**, and that recording was development data
   for tp3. Heart-rate ICC rests on about 10 windows.
2. **No ring-shaped device and no patient study.** All own recordings come from the reference
   board, the ring-format development board or the test board.
3. **No live phone + board session.** The app has run only on replayed recordings.
4. **Amplitude is unresolved:** the signal is about 10× smaller than expected on the nominal
   scale, with the calibration-source routing as the leading suspect (datasheet p.16, p.35). No
   millivolt or morphology claim; polarity was reversed (lead −II).
5. **Clock drift between boards is not measured.** SYNC was never wired; 105 s gives a drift fit
   no power.
6. **Quality thresholds** (kSQI, pSQI) are literature values, not calibrated on our hardware.
   The artifact check rests on one episode and one burst.
7. **tp3 limits:** peak alternation beyond ±39 ms (INCART patient 24); a constant offset after
   a polarity flip; RMSSD slightly low (−0.15 ms median).
8. **Firmware limits** from §6.6: FIFO overflow is invisible on the host; no index or ETAG over
   BLE; the current source has not been flashed.
9. **Public-data analytics:** ectopic and AF are Python only; DS2 is not truly held out;
   breathing coverage is low and uneven (41% of windows; per-subject median 16%).

**Future work (Phase II plan and `docs/MIDTERM_PLAN.md`; state as planned, not done):**

- Bench session 1: swap the electrode clips (lead II), run the `d`/`e`/`c` calibration A/B for
  amplitude, a 10-minute dual capture with the phone live, and wire SYNC for drift.
- Bring up the flex PCB. It has two electrodes and no body reference, so the firmware will need
  the internal lead bias (`EN_RBIAS`).
- Our own post-clip-swap recordings are the **next held-out set** for beat timing (INCART and all
  of MIT-BIH are spent).
- Multi-subject finger vs chest at rest and in light motion; calibrate the quality thresholds
  on it.
- Port the AF screen and ectopic count to the phone with parity tests; add the sample index to
  the BLE packet.
- PPG, GSR and temperature on our hardware (pulse arrival time on the shared index clock),
  validated before being shown.

---

## 13. References

The core set is cited in the Phase-I report (`docs/report/main.tex`). Items marked † are added
here; check them against the paper before printing.

**Algorithms and standards**

1. J. Pan, W. J. Tompkins, "A real-time QRS detection algorithm," *IEEE Trans. Biomed. Eng.*,
   BME-32(3):230–236, 1985.
2. ANSI/AAMI EC57:2012, *Testing and reporting performance results of cardiac rhythm and ST
   segment measurement algorithms*.
3. Task Force of the ESC and NASPE, "Heart rate variability: standards of measurement,
   physiological interpretation and clinical use," *Circulation* 93(5):1043–1065, 1996.
4. N. R. Lomb, *Astrophys. Space Sci.* 39:447–462, 1976; J. D. Scargle, *Astrophys. J.*
   263:835–853, 1982.
5. C.-K. Peng et al., "Quantification of scaling exponents and crossover phenomena in
   nonstationary heartbeat time series," *Chaos* 5(1):82–87, 1995 (DFA α1 on boxes 4–16, p.85).
6. J. S. Richman, J. R. Moorman, *Am. J. Physiol. Heart Circ. Physiol.* 278(6):H2039–H2049, 2000
   (sample entropy).
7. D. E. Lake, J. R. Moorman, *Am. J. Physiol. Heart Circ. Physiol.* 300(1):H319–H325, 2011
   (coefficient of sample entropy). Note: `algorithms/af.py` says its cosen was written from the
   published idea and not checked line by line against the paper.
8. R. J. Ellis et al., "A careful look at ECG sampling frequency and R-peak interpolation on
   short-term measures of HRV," *Physiol. Meas.* 36(9):1827–1852, 2015.
9. G. E. Billman, "The LF/HF ratio does not accurately measure cardiac sympatho-vagal balance,"
   *Front. Physiol.* 4:26, 2013.
10. Q. Li, R. G. Mark, G. D. Clifford, "Robust heart rate estimation from multiple asynchronous
    noisy sources using signal quality indices and a Kalman filter," *Physiol. Meas.*
    29(1):15–32, 2008 (kSQI, pSQI).
11. J. M. Bland, D. G. Altman, *Lancet* 327(8476):307–310, 1986.
12. L. I.-K. Lin, "A concordance correlation coefficient to evaluate reproducibility,"
    *Biometrics* 45(1):255–268, 1989.
13. † P. E. Shrout, J. L. Fleiss, "Intraclass correlations: uses in assessing rater
    reliability," *Psychol. Bull.* 86(2):420–428, 1979 (the ICC(2,1) form `agreement.py` uses).
14. † M. Brennan, M. Palaniswami, P. Kamen, "Do existing measures of Poincaré plot geometry
    reflect nonlinear features of heart rate variability?," *IEEE Trans. Biomed. Eng.*
    48(11):1342–1347, 2001 (SD1/SD2; cited in the code).
15. † R. Bristow-Johnson, "Cookbook formulae for audio EQ biquad filter coefficients" (the biquad
    design in `EcgFilter.kt` and `pan_tompkins.py`).
16. P. de Chazal, M. O'Dwyer, R. B. Reilly, *IEEE Trans. Biomed. Eng.* 51(7):1196–1206, 2004
    (inter-patient split).

**Databases**

17. G. B. Moody, R. G. Mark, "The impact of the MIT-BIH Arrhythmia Database," *IEEE Eng. Med.
    Biol. Mag.* 20(3):45–50, 2001.
18. A. L. Goldberger et al., "PhysioBank, PhysioToolkit, and PhysioNet," *Circulation*
    101(23):e215–e220, 2000 (also the source cited for INCART).
19. M. A. F. Pimentel et al., *IEEE Trans. Biomed. Eng.* 64(8):1914–1923, 2017 (BIDMC).
20. G. D. Clifford et al., "AF classification from a short single lead ECG recording: the
    PhysioNet/Computing in Cardiology Challenge 2017," *Proc. CinC* 44, 2017.
21. G. B. Moody, R. G. Mark, "A new method for detecting atrial fibrillation using R-R
    intervals," *Proc. Comput. Cardiol.* 10:227–230, 1983 (AFDB).
22. † G. B. Moody, W. E. Muldrow, R. G. Mark, "A noise stress test for arrhythmia detectors,"
    *Comput. Cardiol.* 11:381–384, 1984 (NST).
23. P. Schmidt et al., "Introducing WESAD, a multimodal dataset for wearable stress and affect
    detection," *Proc. ICMI*, 400–408, 2018 (usable for scientific, non-commercial work with credit).

**Hardware and tools**

24. Maxim Integrated, *MAX30003 datasheet*, Rev 3 (pages cited in
    `docs/MAX30003_datasheet_check.md`).
25. D. Makowski et al., "NeuroKit2," *Behav. Res. Methods* 53:1689–1696, 2021.
26. A. Greco et al., "cvxEDA," *IEEE Trans. Biomed. Eng.* 63(4):797–804, 2016 (WESAD panel only).

**Context (introduction only):** Briosa e Gala et al., *Heart Rhythm O2*, 2025 (ring and watch
single-lead ECG); Mahajan et al., *Anatol. J. Cardiol.* 29(5):228–241, 2025 (smartphone ECG).
Do not quote their numbers as comparisons with ours: the setups differ.

---

## 14. Claim-verification table

Status levels, strongest last:

- **Planned:** not built.
- **Provisional:** built, but rests on uncalibrated values or a single anecdote.
- **Implemented:** code exists.
- **Unit-tested:** tests pass, including parity tests. This says the code does what the reference
  does, not that it is right.
- **Experimentally evaluated:** measured on data, DEV or own recordings.
- **Independently validated:** run once on HELD-OUT or EXTERNAL data with parameters frozen
  beforehand. **No result here has been validated by a third party or clinically.**

| # | Claim (poster wording) | Status | Evidence / source | Data | Caveat that must travel with it |
|---|---|---|---|---|---|
| 1 | One firmware source builds for both boards; decoding, registers, rate and timestamping are identical | Implemented | `sketch.ino` (pin block per target) | – | Boards run the 29 Sep build; the current source is not flashed |
| 2 | FIFO decoded with ETAG; overflow detected and reset | Implemented; datasheet-checked | `sketch.ino`, `docs/MAX30003_datasheet_check.md` #1–5 | – | Overflow loses samples without an index gap |
| 3 | Interrupt-driven acquisition at 256 SPS with no FIFO overflow | Experimentally evaluated (firmware counters) | `captures/20260819_153726_gate_rest_01.log`: ovf 0, depth ≤ 5/32 | one 5-min capture, 19 Aug, older build | Firmware-reported; no saved host check of that capture |
| 4 | 0 missing, 0 duplicate samples over USB on both boards | Experimentally evaluated | `analysis/integrity_20260929_152557_linktest_noelectrodes.txt` | one 174.61 s capture, no electrodes | USB only; BLE integrity not measured |
| 5 | Noise floor matches the datasheet's typical value | Experimentally evaluated | `analysis/amplitude_linktest_noelectrodes.txt`: 1.42 vs 1.39 codes | ring-format board, 164 s | Nominal scale unverified; reference board 3.22 codes |
| 6 | BLE packets carry a sequence number; the phone keeps time across losses | Implemented; Unit-tested (`BeatDetectorParityTest` artifact + lost-packets case, `ReconnectTest`) | `EcgPipeline.kt`, `pan_tompkins.py skip()` | – | Never run live; seq ambiguous beyond 256 lost packets |
| 7 | Causal filter delay 7.8 ms (2 samples) | Experimentally evaluated (development) | `EcgFilter.kt` docstring | one 14 s finger capture | **No saved analysis file**; quote as "measured during development" |
| 8 | Detector Se 99.78%, P+ 99.32% | **Independently validated** (held-out, once) | `analysis/heldout_ec57_tp2.1.txt` | 32 MIT-BIH records, 73,159 beats | tp2.1 timing; record 207 P+ 80.88%; MIT-BIH now all DEV |
| 9 | With the bSQI 0.9 gate: Se 99.82%, P+ 99.89% | Independently validated | same | same | 2.4% of recording time rejected; bSQI is benchmark-only, not on the phone |
| 10 | Search-back localisation fix raised dev Se/P+ 98.50/97.31 → 99.52/98.32 | Experimentally evaluated | `ec57_benchmark.txt`, `ec57_benchmark_tp2.txt` | 12 DEV records | DEV |
| 11 | Phone detector identical to the Python reference | Unit-tested | `BeatDetectorParityTest`; `analysis/tp3_port_check.txt` (100/100, 5.8e-11 samples) | MIT-BIH + tb01/tb02 fixtures | Equality with the reference, not correctness |
| 12 | Causal filtering makes the 5–15 Hz timing point jump between QRS lobes | Experimentally evaluated | `fiducial_..._dual03_..._v2.txt`: 48 of 179 causal vs 1 of 179 zero-phase | dual03, one subject | Shown on one recording; the mechanism is consistent with E4 |
| 13 | Lobe-jumping doubled finger RMSSD (36.7 vs 18.3 ms) | Experimentally evaluated | same + `tp3_own_recordings.txt` | dual03 | The 18.3 ms comparison value is chest with tp3 |
| 14 | RMSSD² inflates by 6σ² for independent timing errors | Theoretical (derivation) | E4 | – | Independence assumed; σ ≈ 13 ms is derived |
| 15 | tp3 times beats with no polarity decision | Implemented; Unit-tested | `pan_tompkins.py`, `BeatDetector.kt`, `BeatDetectorConfigTest` | – | Constant offset after a polarity flip |
| 16 | tp3 finger–chest RR LoA ±1.8 ms; finger RMSSD 17.9 vs chest 18.3 ms | Experimentally evaluated | `tp3_own_recordings.txt` | dual03, **DEV for tp3** | One subject, 105 s |
| 17 | tp3 cut INCART patients under 50% usable intervals from 11 to 2 of 32 | **Independently validated** (held-out, once) | `tp3_incart_heldout.txt` | 75 records / 32 patients | Algorithmic annotations; patient 24 regression |
| 18 | tp3 mean absolute RMSSD error on INCART 2.08 → 1.22 ms | Independently validated (relative) | same | same | Compares timing points, not absolute accuracy |
| 19 | tp3 restores HRV on biphasic-QRS records (0% → 82–99%) | Experimentally evaluated | `tp3_mitdb48_dev.txt`, `heldout_coverage_diagnosis.txt` | MIT-BIH 111, 117, 215, 230 (DEV) | DEV |
| 20 | tp3 does not change detection | Experimentally evaluated | `ec57_benchmark_tp3.txt` | 48 MIT-BIH (DEV) | Not a held-out result |
| 21 | Finger–chest HR bias +0.03 bpm, LoA −0.10…+0.15, ICC 0.9998 | Experimentally evaluated | `agreement_..._dual03_..._ref_tp2.txt` | dual03, about 10 windows | tp2; one subject; ICC on a narrow HR range |
| 22 | The third (reference) electrode is required at the finger | Provisional | `analysis/mains_share_dual01-03.txt`: mains median 1.0% / 2.3% in dual03 vs 91.8% in dual01 | 3 recordings, one subject | dual01's cable configuration is not recorded in the file; the "0.4% → 43%" figure in `CLAUDE.md` has no saved file |
| 23 | HRV functions equal neurokit2 on the same NN series | Independently validated (arithmetic) | `hrv_vs_neurokit_mitdb_heldout.txt` | 192 held-out windows | Arithmetic only; LF/HF differs ≤ 3.2% from the grid |
| 24 | Each HRV measure is withheld below its minimum window | Implemented; Unit-tested (117 Python tests) | `algorithms/config.json`, `tests/` | – | – |
| 25 | LF/HF withheld below 95% coverage because holes bias band power | Experimentally evaluated (simulation) | `hrv_min_window_simulation.txt` (HF +15.9% / +30.3% at ~90%) | **synthetic** | Simulation only |
| 26 | Quality gate rejects electrode-settling transients without rejecting clean ECG | Experimentally evaluated | `sqi_artifact_dev.txt`, `app_quality_gate_replay.txt` | **DEV only** | One episode and one burst |
| 27 | Quality thresholds (kSQI 5, pSQI 0.10) | Provisional | `sqi_config.json` | – | Literature values, not calibrated |
| 28 | Heart rate shown only on GOOD; live HR never more than 5 bpm off a reference | Unit-tested; Experimentally evaluated (replay) | `analysis/app_live_hr.txt` (0 of 1,359) | dual03, tb02 replayed | Replay, not live |
| 29 | Breathing rate MAE 0.50 br/min | Independently validated (held-out, once) | `breathing_bidmc_heldout.txt` | BIDMC, 23 subjects | Reported in 41% of windows; ICU patients; no 6/min data |
| 30 | V-beat Se 88.36%, P+ 82.67% | Experimentally evaluated | `ectopic_mitdb_ds2.txt` | MIT-BIH DS2 | **Not truly held out**; Python only |
| 31 | AF screen Se 92.22%, Sp 96.80% | Independently validated (external, once) | `af_afdb_external.txt` | AFDB, 23 patients | Screening, not diagnosis; 97.16% coverage; Python only |
| 32 | Arousal model balanced accuracy 93.3% (wrist only) | Experimentally evaluated (LOSO) | `wesad_evaluation.txt` | WESAD, 15 subjects | DEV for the feature code; order confound; not our hardware; no stress claim |
| 33 | Android suite: 156 tests, 0 failures | Unit-tested | `analysis/phase1_test_run.txt` | – | 6 skipped (need an uncommitted asset) |
| 34 | The app runs live with the ring board | **Planned** | `android_app/LIVE_TEST.md` | – | Never run |
| 35 | ECG amplitude in mV; morphology | **Planned** (blocked) | `docs/amplitude_investigation.md` | – | Scale unverified; lead −II |
| 36 | Oscillator drift between boards | **Planned** | – | – | Not measured; do not quote −16.7 ppm |
| 37 | PPG / GSR / temperature / IMU streams | Implemented, never run | `sketch.ino` (10 Nov), `docs/bench_session_1.md` | – | Not flashed; no result |
| 38 | Ring flex PCB | Not this work; fabrication reported, not brought up | `docs/report/main.tex` §III-C | – | Lab hardware team's design; credit them |
| 39 | Supervised patient study | **Planned** | Project plan, November | – | Not done; ethics status unknown |

---

## 15. Open questions for the author (resolve before the poster is drawn)

1. **Flex PCB status.** The report (24 Nov) says "fabricated and its assembly is under way";
   `CLAUDE.md`'s board table says "not yet built". Which is current? It was designed by the
   lab's hardware team: should the poster show it at all, and with what credit line?
2. **Ethics application.** Was it submitted? The plan lists it as a September deliverable.
3. **WESAD panel.** It is real work, but it is on public data with another lab's devices. Keep
   it (one row in the analytics table) or drop it to give tp3 more room? The recommendation is
   one row.
4. **Quick win before printing, optional:** run `./integrity.py` on
   `captures/20260819_153726_gate_rest_01.csv`. If it is clean on the host, the September
   milestone ("five-minute continuous capture with no data loss") has host-side evidence rather
   than firmware counters only.
5. **Naming on the poster:** dual03's "ring" file is the chest channel. Use "board A (ESP32-C3)
   / board B (ESP32-WROOM)" or "chest / finger", never "ring" for the chest.
6. **Author line and venue:** poster size, orientation and template (A0 portrait vs landscape;
   institute template?).
