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
| BIDMC PPG and Respiration Dataset | ODC-By 1.0 | ✅ 23 Oct 2026, PhysioNet | 53 recordings of 8 min at 125 Hz | Respiration rate from ECG (item 4) |
| MIT-BIH Arrhythmia Database | ODC-By 1.0 | ✅ 23 Oct 2026, PhysioNet | 48 records from 47 subjects at 360 Hz | Detector benchmark and timing-point check: 12 records are the development subset, the other 36 the held-out test (`tp2_config.json`) |
| WESAD | **to be checked** | not yet (not hosted on PhysioNet) | | Stress from HRV (item 5); do not use until the licence is known |

## Notes

- **Sample rates differ from ours.** The confirmed public datasets run from 125 Hz (BIDMC) to
  1000 Hz (BUT QDB), MIT-BIH at 360 Hz; our boards record at 256 Hz. Models have to be trained and tested on data
  resampled to 256 Hz, and the resampling belongs inside the evaluation.
- **ODC-By** and **CC BY 4.0** both require attribution. Cite each dataset as its page asks,
  and cite PhysioNet itself for PhysioNet-hosted data.
- **MIT-BIH is split.** The 12 records 100, 101, 103, 105, 106, 108, 109, 119, 203, 208, 222 and
  228 are the **development** subset: every detector and tp2 parameter was tuned on them. The other
  36 are the **held-out** test, evaluated once with the parameters frozen in `tp2_config.json`.
  Every MIT-BIH figure must say which set it comes from.
