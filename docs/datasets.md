# External datasets

Public datasets used, or planned, for algorithm development. None of them is committed to this
repository: `data/` is gitignored, and each dataset is downloaded locally.

Licences as recorded on 23 Oct 2026. Before publishing results or redistributing anything
derived from a dataset, confirm the licence on the dataset's own page and fill in the
`Confirmed` column.

| Dataset | Licence | Confirmed | Planned use |
|---|---|---|---|
| PhysioNet/CinC Challenge 2017 (AF classification, single-lead) | ODC-By | not yet | Rhythm / AF detection (item 3) |
| BUT QDB (Brno University of Technology ECG Quality Database) | CC BY 4.0 | not yet | Learned signal-quality model (item 2) |
| MIT-BIH Noise Stress Test Database (NSTDB) | ODC-By | not yet | Real electrode-motion / muscle / baseline noise for quality and robustness tests (item 2) |
| BIDMC PPG and Respiration Dataset | ODC-By | not yet | Respiration rate from ECG (item 4) |
| WESAD | **unknown, to be checked** | not yet | Stress from HRV (item 5); do not use until the licence is known |
| MIT-BIH Arrhythmia Database | **not recorded, to be checked** | not yet | Already in use: detector benchmark (`benchmark_mitdb.py`, 12-record subset in `data/mitdb/`) and fiducial check (`fiducial.py`) |

## Notes

- **ODC-By** and **CC BY 4.0** both require attribution. Cite each dataset as its page asks,
  and cite PhysioNet itself for PhysioNet-hosted data.
- The detector benchmark uses **12 of the 48 MIT-BIH Arrhythmia records** (100, 101, 103, 105,
  106, 108, 109, 119, 203, 208, 222, 228). Every MIT-BIH figure in this project refers to that
  subset, not the full database.
