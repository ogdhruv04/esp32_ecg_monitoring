---
title: "A ring that records your heartbeat properly"
eyebrow: "Project Brief · 4-Month Timeline"
standfirst: "We are building a ring that captures a real electrocardiogram from your finger and sends it to your phone. Over four months it goes from a working prototype to a device with measured, proven accuracy — and a steadily widening set of things it can tell you about your health."
footer: "Prepared for project stakeholders · Revision D · Detailed engineering plan available on request."
---

## What we are building

An electrocardiogram — an ECG — measures the electrical activity your heart produces with every beat. It is what a hospital uses, and the most reliable way to see how a heart is actually behaving. A clinical ECG is accurate but means electrodes on your chest; a smartwatch is convenient but mostly reads your pulse optically, which is an approximation.

Our ring aims at the gap: a genuine electrical heart reading, taken in thirty seconds, from something you already wear all day — with pulse, skin temperature, skin response and motion tracked continuously alongside it.

::: status
### Where we are today

The prototype works end to end: the sensor captures a heart signal, sends it wirelessly, and our phone app displays it live. We have also just corrected a significant flaw in how the sensor data was being read — one that would have quietly corrupted every measurement we took.

A plausible-looking heart trace can be produced from electrical noise alone, and nothing about it looks wrong from the inside. The work ahead is proving, against hospital-grade equipment, that what the ring reports is real — and then widening what it can report.
:::

---

## The four months

::: timeline

::: phase
**Month 1**

### A heartbeat we can trust

::: gains
**Software Milestones**

- Sensor front end running at 256 samples/sec, with **zero data-loss events across a 5-minute capture** and sample timing jitter **under 2 ms**
- Filtering pipeline v1 — baseline-wander removal (0.5 Hz high-pass), mains-noise notch (50 Hz), high-frequency limit (40 Hz); zero-phase offline, causal on-device with its delay measured
- Heartbeat detection implemented and benchmarked against cardiologist-labelled public recordings: **≥99% of beats found, ≥99% of detections correct**
- Time-synchronised dual recording — ring and medical reference aligned to **under 50 ms**
- Resting heart rate agreement vs reference: **bias under 2 bpm, limits of agreement within ±5 bpm**
- Beat-to-beat interval export, with heart rate variability (RMSSD, SDNN, pNN50) computed from it
- Raw session capture to phone storage, so every later result can be re-derived from source data
:::

::: hw
**Hardware Milestones**

- _[placeholder — electrode design: material, contact area, plating]_
- _[placeholder — ring PCB revision and form factor]_
- _[placeholder — power budget and battery selection]_
- _[placeholder]_
:::
:::

::: phase
**Month 2**

### Readings that survive real life

::: gains
**Software Milestones**

- Motion sensors integrated — accelerometer and gyroscope sampled on the **same clock and timestamps** as the heart signal
- Motion-artifact suppression using the motion sensors as a reference, with **measured improvement in beat detection on movement recordings** against the unfiltered baseline
- Signal quality score v1 — combining signal shape, in-band power, agreement between two independent beat detectors, and motion energy; **rejection rate reported as a headline number**
- Beat detection characterised across graded noise levels using a purpose-built public noise database
- Accuracy re-measured with the quality score applied: **accuracy gained vs percentage of readings rejected**
- Heart rate and variability validated **during walking and light exercise**, not only at rest
- Breathing rate derived from the way each breath modulates the heart signal
- Pulse sensor pipeline live; **pulse rate vs ECG heart rate agreement quantified**
- Skin temperature and skin conductance logged, trended, and time-aligned with everything else
- Stress and arousal index v1, benchmarked against a public multi-sensor dataset
:::

::: hw
**Hardware Milestones**

- _[placeholder — electrode contact under movement]_
- _[placeholder — sensor placement and mechanical fit]_
- _[placeholder — enclosure / sealing]_
- _[placeholder]_
:::
:::

::: phase
**Month 3**

### Screening, and sensors that cover for each other

::: gains
**Software Milestones**

- Rhythm-irregularity feature set implemented — normalised variability, distribution entropy, sample entropy, and beat-interval scatter geometry
- Atrial fibrillation screening baseline validated against annotated public recordings of the condition: **sensitivity and specificity both reported**
- **False-alarm rate measured on our own healthy volunteers** — every flag raised there is by definition incorrect
- Known failure mode characterised: extra beats that mimic an irregular rhythm
- Heart and pulse sensors fused with quality weighting — **accuracy under degraded conditions vs either sensor alone**
- Blood oxygen saturation from the pulse sensor, compared against a reference oximeter
- Overnight recovery summary combining heart rate, variability, temperature and movement
- Optional machine-learning classifier — trained with strict participant separation, and **only adopted if it beats the simpler baseline on the same held-out data**
:::

::: hw
**Hardware Milestones**

- _[placeholder — optical sensor window and skin coupling]_
- _[placeholder — thermal path for temperature accuracy]_
- _[placeholder — antenna and wireless range in worn position]_
- _[placeholder]_
:::
:::

::: phase
**Month 4**

### On the device, in the app, and on the record

::: gains
**Software Milestones**

- Full pipeline running **on-device and inside the app**, not in research scripts — with **per-reading latency and battery cost measured**
- End-to-end validation: raw signal in, heart rate / variability / quality score / rhythm flag out, checked against every reference recording from Months 1–3
- Coverage testing across **finger positions, hand sizes, skin tones and times of day**, with results reported separately for the electrical and optical sensors
- Session history, trends and data export in the app
- Automated regression suite, so any future firmware or algorithm change re-verifies every number above
- **Final validation report** — every metric with its measured value, and every user-facing number traceable to a specific measurement
- Battery life per typical day of use, measured rather than estimated
:::

::: hw
**Hardware Milestones**

- _[placeholder — final assembly and manufacturability]_
- _[placeholder — durability, water resistance, charging]_
- _[placeholder — production-intent build]_
- _[placeholder]_
:::
:::

:::

---

## Where that leaves us

After four months the ring is no longer a prototype producing a plausible line on a screen. It is an instrument with a known margin of error — reporting heart rate, heart rate variability, breathing rate, blood oxygen, skin temperature, stress and recovery, and screening for an irregular rhythm that matters clinically.

Just as importantly, every one of those numbers arrives with evidence behind it. That report is the first thing any clinical partner, regulator or investor asks to see, and it is what turns a working device into a credible one.
