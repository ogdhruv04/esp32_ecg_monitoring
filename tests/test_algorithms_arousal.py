"""Baseline z-scoring, the model and leave-one-subject-out
(docs/wesad_plan.md, sections 5 and 6), on synthetic feature tables."""
import math
import numpy as np
import pandas as pd
import pytest
from algorithms import arousal, NNSeries

COLS = arousal.model_columns(["bvp", "temp_wrist"])


def table(seed, shift=2.0, n=14, scale=None, offset=None):
    """One subject's windows. Every subject has its own units (offset, scale);
    stress moves each feature by `shift` reference sds."""
    rng = np.random.default_rng(seed)
    scale = rng.uniform(0.5, 20.0, len(COLS)) if scale is None else scale
    offset = rng.uniform(-50, 50, len(COLS)) if offset is None else offset
    rows = []
    for part, mean in [("reference", 0.0), ("baseline", 0.0), ("stress", shift), ("amusement", 0.0)]:
        for i in range(n):
            x = offset + scale * (mean + rng.standard_normal(len(COLS)))
            rows.append(dict(part=part, t0=30.0 * i, t1=30.0 * i + 180.0, **dict(zip(COLS, x))))
    return pd.DataFrame(rows)


def tables(k=6, **kw):
    return {f"S{i}": table(i, **kw) for i in range(k)}


def test_columns_of_blocks_and_models():
    assert arousal.columns("eda_wrist") == ["eda_wrist.scl", "eda_wrist.scl_slope", "eda_wrist.scr_rate", "eda_wrist.phasic_mean"]
    assert arousal.columns("ecg_time") == ["ecg.hr", "ecg.ln_rmssd", "ecg.pnn50", "ecg.ln_sdnn", "ecg.ln_sd2"]
    assert set(arousal.columns("ecg_time")) < set(arousal.columns("ecg_full"))
    for name, blocks in arousal.A["models"].items():
        assert len(arousal.model_columns(blocks)) == len(set(arousal.model_columns(blocks))), name
    assert arousal.columns("bvp_primary") == ["bvp.pr", "bvp.ln_amp"]
    # the 23 Nov rule-3 amendment: ECG-time 5 + BVP pr, ln_amp 2 + EDA 4 + TEMP 1; as frozen 16 Nov, 8 + 4 + 4 + 1
    assert len(arousal.model_columns(arousal.A["models"]["All four"])) == 12
    assert len(arousal.model_columns(arousal.A["models_as_frozen_16_nov"]["All four"])) == 17


def test_reference_stats_need_enough_windows():
    t = table(0)
    t.loc[(t["part"] == "reference") & (t.index >= 4), COLS[0]] = np.nan      # 4 reference windows left
    mu, sd = arousal.reference_stats(t, COLS)
    assert math.isnan(mu[COLS[0]]) and math.isnan(sd[COLS[0]]) and np.isfinite(mu[COLS[1]])
    ref = t.loc[t["part"] == "reference", COLS[1]]
    assert math.isclose(mu[COLS[1]], ref.mean()) and math.isclose(sd[COLS[1]], ref.std(ddof=1))


def test_zscore_uses_only_the_reference_and_the_floor_and_clips():
    t = table(1)
    mu, sd = arousal.reference_stats(t, COLS)
    none = pd.Series(0.0, index=COLS)
    z = arousal.zscore(t, COLS, mu, sd, none)
    ref = z.loc[z["part"] == "reference", COLS]
    assert np.allclose(ref.mean(), 0, atol=1e-9) and np.allclose(ref.std(ddof=1), 1)
    big = pd.Series(sd.to_numpy() * 4, index=COLS)
    z4 = arousal.zscore(t, COLS, mu, sd, big)
    assert np.allclose(z4[COLS].to_numpy() * 4, z[COLS].to_numpy())
    t2 = t.copy(); t2.loc[t2.index[-1], COLS[0]] = 1e9
    assert arousal.zscore(t2, COLS, mu, sd, none)[COLS[0]].iloc[-1] == arousal.A["z_clip"]


def test_flat_reference_without_a_floor_is_withheld_not_infinite():
    t = table(2)
    t.loc[t["part"] == "reference", COLS[0]] = 7.0
    mu, sd = arousal.reference_stats(t, COLS)
    z = arousal.zscore(t, COLS, mu, sd, pd.Series(0.0, index=COLS))
    assert z.loc[z["part"] == "stress", COLS[0]].isna().all()
    z = arousal.zscore(t, COLS, mu, sd, pd.Series(1.0, index=COLS))
    assert z.loc[z["part"] == "stress", COLS[0]].notna().all()


def test_floor_is_half_the_median_training_sd():
    sds = [pd.Series([1.0, 10.0], index=["a", "b"]), pd.Series([3.0, np.nan], index=["a", "b"]),
           pd.Series([5.0, 30.0], index=["a", "b"])]
    f = arousal.sd_floor(sds)
    assert f["a"] == 1.5 and f["b"] == 10.0


def test_loso_separates_subjects_that_differ_in_units():
    rows, folds = arousal.loso(tables(), COLS)
    assert set(rows["part"]) == {"baseline", "stress", "amusement"}          # the reference is never classified
    assert len(folds) == 6 and all(f["n_train"] == 5 * 28 for f in folds.values())
    s = arousal.scores(rows)
    assert s["se"] > 0.9 and s["sp"] > 0.9 and s["auc"] > 0.97
    assert s["rejected_positive"] == 0 and s["n_positive"] == 6 * 14
    assert arousal.called_positive(rows, "amusement")["share"] < 0.15


def test_no_shift_gives_chance():
    rows, _ = arousal.loso(tables(k=8, shift=0.0), COLS)
    assert 0.3 < arousal.scores(rows)["auc"] < 0.7


def test_the_test_subject_does_not_reach_its_own_fold():
    a = tables()
    b = {s: t.copy() for s, t in a.items()}
    k = b["S0"]["part"].isin(["baseline", "stress", "amusement"])
    b["S0"].loc[k, COLS] = 123.0                                             # only S0's classified windows change
    _, fa = arousal.loso(a, COLS)
    _, fb = arousal.loso(b, COLS)
    assert fa["S0"]["coef"] == fb["S0"]["coef"] and fa["S0"]["intercept"] == fb["S0"]["intercept"]
    assert fa["S1"]["coef"] != fb["S1"]["coef"]


def test_incomplete_windows_are_rejected_and_counted():
    t = tables()
    idx = t["S3"].index[t["S3"]["part"] == "stress"][:7]
    t["S3"].loc[idx, COLS[2]] = np.nan
    rows, _ = arousal.loso(t, COLS)
    s3 = rows[(rows["subject"] == "S3") & (rows["part"] == "stress")]
    assert (~s3["complete"]).sum() == 7 and s3.loc[~s3["complete"], "pred"].isna().all()
    s = arousal.scores(rows)
    assert math.isclose(s["rejected_positive"], 7 / 84) and s["n_positive"] == 77 and s["rejected_negative"] == 0


def test_scores_arithmetic():
    rows = pd.DataFrame(dict(subject="S1", t0=0.0,
                             part=["stress"] * 5 + ["baseline"] * 5,
                             complete=[True, True, True, True, False] + [True] * 5,
                             index=[2, 1, 3, -1, np.nan, -2, -3, 1, -1, -4.0],
                             pred=[1, 1, 1, 0, np.nan, 0, 0, 1, 0, 0]))
    s = arousal.scores(rows)
    assert (s["tp"], s["fn"], s["tn"], s["fp"]) == (3, 1, 4, 1)
    assert s["se"] == 0.75 and s["sp"] == 0.8 and s["ppv"] == 0.75 and math.isclose(s["balanced_accuracy"], 0.775)
    assert s["rejected_positive"] == 0.2 and s["rejected_negative"] == 0.0
    assert math.isclose(s["auc"], 18 / 20)       # 20 pairs: 16 ordered right, 2 wrong, 2 ties counted as half
    assert math.isclose(s["accuracy"], 7 / 9)                                 # the rejected window is not counted
    assert math.isclose(s["f1_positive"], 6 / 8) and math.isclose(s["f1_macro"], (6 / 8 + 8 / 10) / 2)


def test_common_windows_and_per_subject():
    rows = pd.DataFrame(dict(subject=["S1"] * 4 + ["S2"] * 2, part=["stress", "stress", "baseline", "baseline", "stress", "stress"],
                             t0=[0.0, 30.0, 0.0, 30.0, 0.0, 30.0], complete=[True, True, True, False, True, True],
                             index=[1.0, 2.0, -1.0, np.nan, 1.0, -1.0], pred=[1, 1, 0, np.nan, 1, 0]))
    other = rows.copy(); other["complete"] = [True, False, True, True, True, True]
    c = arousal.common_windows({"a": rows, "b": other})
    assert len(c["a"]) == 4 and set(c["a"]["t0"][c["a"]["subject"] == "S1"]) == {0.0}
    ps = arousal.per_subject(rows)
    assert ps.loc["S1", "balanced_accuracy"] == 1.0 and ps.loc["S1", "n_negative"] == 1
    assert ps.loc["S2", "se"] == 0.5 and math.isnan(ps.loc["S2", "sp"]) and math.isnan(ps.loc["S2", "balanced_accuracy"])


def test_one_class_in_training_is_an_error():
    t = tables(k=3)
    for s in t:
        t[s] = t[s][t[s]["part"] != "stress"]
    with pytest.raises(ValueError, match="only one class"):
        arousal.loso(t, COLS)


def test_bootstrap_resamples_subjects():
    rows, _ = arousal.loso(tables(), COLS)
    ci = arousal.bootstrap(rows)
    s = arousal.scores(rows)
    assert ci["se"][0] <= s["se"] <= ci["se"][1] and ci["auc"][0] <= ci["auc"][1] <= 1.0


def test_ecg_features_follow_the_hrv_minimums():
    rng = np.random.default_rng(0)
    full, info = arousal.ecg_features(NNSeries.from_intervals(800 + 30 * rng.standard_normal(215)))
    assert all(np.isfinite(v) for v in full.values()) and info["coverage"] == 1.0
    assert math.isclose(full["hr"], 75.0, rel_tol=0.02)
    short, _ = arousal.ecg_features(NNSeries.from_intervals(800 + 30 * rng.standard_normal(100)))   # 80 s
    assert np.isfinite(short["hr"]) and np.isfinite(short["ln_rmssd"])
    assert math.isnan(short["ln_sdnn"]) and math.isnan(short["ln_lf"]) and math.isnan(short["dfa_alpha1"])
    tiny, _ = arousal.ecg_features(NNSeries.from_intervals([800.0] * 40))
    assert all(math.isnan(v) for v in tiny.values())
