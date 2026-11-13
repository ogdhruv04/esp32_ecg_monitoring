# External datasets

Public datasets used, or planned, for algorithm development. None of them is committed to this
repository: `data/` is gitignored, and each dataset is downloaded locally.

Rows marked confirmed were checked against the dataset's PhysioNet page on 23 Oct 2026.
Confirm the others the same way before using them, and record the date here.

| Dataset | Licence | Confirmed | Content (as confirmed) | Planned use |
|---|---|---|---|---|
| PhysioNet/CinC Challenge 2017 (AF classification, single lead) | ODC-By 1.0 | ✅ 23 Oct 2026, PhysioNet | 8,528 training recordings at 300 Hz | Rhythm / AF detection (item 3) |
| BUT QDB (Brno University of Technology ECG Quality Database) | CC BY 4.0 | ✅ 23 Oct 2026, PhysioNet | 18 recordings from 15 subjects at 1000 Hz | Learned signal-quality model (item 2) |
| MIT-BIH Noise Stress Test Database (NSTDB) | ODC-By 1.0 | ✅ 23 Oct 2026, PhysioNet | | Real electrode-motion / muscle / baseline noise for quality and robustness tests (item 2) |
| BIDMC PPG and Respiration Dataset | ODC-By 1.0 | ✅ 23 Oct 2026 and again 11 Nov 2026, PhysioNet | 53 recordings of 8 min at 125 Hz, lead II ECG in every one, breaths marked by two annotators. **46 subjects, not 53** (see notes) | Respiration rate from ECG: `validate_breathing_bidmc.py`, split by subject in `algorithms/config.json` |
| MIT-BIH Arrhythmia Database | ODC-By 1.0 | ✅ 23 Oct 2026, PhysioNet | 48 records from 47 subjects at 360 Hz | Detector benchmark and timing-point check. **All 48 records are development data from 13 Nov 2026** (see notes) |
| St Petersburg INCART 12-lead Arrhythmia Database | ODC-By 1.0 | ✅ 13 Nov 2026, PhysioNet | 75 half-hour records from 32 patients at 257 Hz, 12 leads, over 175,000 beat annotations | **Held-out** set for beat timing and coverage, replacing the spent MIT-BIH records: `evaluate_tp3.py incart`, protocol in `tp3_candidate.json` |
| WESAD (Wearable Stress and Affect Detection) | No named licence. Its page says: "You may use this data for scientific, non-commercial purposes, provided that you give credit to the owners when publishing any work based on this data." | ✅ 13 Nov 2026, University of Siegen page (`ubi29.informatik.uni-siegen.de/usi/data_wesad.html`) | Not downloaded | **Usable for this project** (scientific, non-commercial), with credit: Schmidt P, Reiss A, Duerichen R, Marberger C, Van Laerhoven K. Introducing WESAD, a multimodal dataset for Wearable Stress and Affect Detection. ICMI 2018. Arousal from HRV and skin signals (item 5). Not usable in anything commercial. |

## Notes

- **Sample rates differ from ours.** The confirmed public datasets run from 125 Hz (BIDMC) to
  1000 Hz (BUT QDB), MIT-BIH at 360 Hz, INCART at 257 Hz; our boards record at 256 Hz. Models have to be trained and tested on data
  resampled to 256 Hz, and the resampling belongs inside the evaluation.
- **ODC-By** and **CC BY 4.0** both require attribution. Cite each dataset as its page asks,
  and cite PhysioNet itself for PhysioNet-hosted data.
- **MIT-BIH is all development data from 13 Nov 2026.** Until then the 12 records 100, 101, 103, 105,
  106, 108, 109, 119, 203, 208, 222 and 228 were the development subset and the other 36 the held-out
  test. Those 36 were used once for tp2.1 (31 Oct, `tp2_config.json`) and once more for the arithmetic
  check of the HRV functions (11 Nov), so they can no longer serve as unseen data, and the biphasic-QRS
  coverage problem was found on them. Results published from them before 13 Nov remain held-out results
  for the parameters that were frozen at the time. Every MIT-BIH figure must still say which records it
  comes from and when.
- **INCART is the held-out set for beat timing.** 32 patients (17 men, 15 women, aged 18-80) tested
  for coronary artery disease; the header of each record gives its patient number, and records of one
  patient come from one Holter recording, so summaries are also given per patient. Its beat
  annotations were placed by an algorithm "in the middle of the QRS complex" and their positions
  were not corrected by hand (database description), so RMSSD from its annotations carries that
  jitter. Downloaded on 13 Nov 2026 to `<main checkout>/data/incartdb` (796 MB, SHA-256 checked).
  Cite the database and PhysioNet as its page asks.
- **BIDMC has repeated subjects.** The paper describes 53 patients, but the `MIMIC II matched wdb ID`
  in `bidmc_csv/bidmc_NN_Fix.txt` shows 46: s03386 has recordings 06–09, s11342 has 20–23 and
  s25323 has 38–39. The development / held-out split in `algorithms/config.json` is by subject
  (23 and 23, 26 and 27 recordings), fixed on 11 Nov 2026 from that metadata before any signal
  was read. Downloaded on 11 Nov 2026 to `<main checkout>/data/bidmc` (WFDB records, `.breath`
  annotations and the `Fix.txt` files, 34 MB, SHA-256 checked against the dataset's `SHA256SUMS.txt`).
  Cite Pimentel et al., *IEEE Trans Biomed Eng* 2017;64(8):1914–1923, and PhysioNet.
