"""Phase 4 -- baselines, walk-forward validation, and the tests that decide
whether anything here is real.

Order of operations matters and is deliberate:

  1. BASELINES FIRST, including two that were missing. The original AR(1) is a
     weak opponent on a non-stationary target: any regressor carrying a trend
     can beat it without containing a single bit of Datadog information. So the
     baseline set now includes AR(1) with a linear trend and ARIMA(1,1,0).
  2. A TREND-ONLY FEATURE, structurally identical to the real candidates but
     containing nothing except a time index. If it scores like `dd_abs`, then
     `dd_abs`'s edge is trend-fitting and the headline must say so. (LOG D27)
  3. THE FULL GRID, 3 features x 4 windows x 2 targets = 24 cells, each with
     its matched control. The window dimension was NOT pre-registered in D24,
     so it is a post hoc degree of freedom and has to be priced. (LOG D26)
  4. A PERMUTATION NULL over the whole grid, to answer: how many of 24 cells
     would show RMSE ratio < 0.9 by chance alone?
  5. DIEBOLD-MARIANO with the Harvey-Leybourne-Newbold small-sample correction,
     plus a bootstrap CI on the RMSE ratio. A point estimate of 0.86 at n=13 is
     not a result until it survives this.

Outputs:
  processed/wf_baselines.csv
  processed/wf_grid.csv
  processed/wf_permutation_null.csv
  processed/wf_significance.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

import analysis_leadlag as ll
import sec_common as sc

FIRST_TRAIN = 12
N_PERM = 1000
N_BOOT = 10000
SEED = 20260814

CANDIDATES = ["dd_rel_plc", "dd_rel", "dd_abs"]
CONTROLS = {"dd_rel_plc": "ctrl_rel_plc", "dd_rel": "plc_rel", "dd_abs": "plc_abs"}
WINDOWS = ["d30", "d45", "d60", "full"]
TARGETS = ["rev_yoy", "beat_vs_guide"]


# --------------------------------------------------------------- frame setup


def frame() -> pd.DataFrame:
    f = ll.build_analysis_frame()
    f["rev_yoy_lag2"] = f["rev_yoy"].shift(2)
    f["rev_musd_lag4"] = f["revenue_musd"].shift(4)
    f["beat_lag1"] = f["beat_vs_guide"].shift(1)
    # Trend regressor: a pure time index. Contains no information about
    # Datadog, only about the passage of time.
    f["trend"] = np.arange(len(f), dtype=float)
    # Guidance-implied YoY, known at the same time as the guidance itself.
    f["guide_implied_yoy"] = f["guide_mid"] / f["rev_musd_lag4"] - 1
    return f


def _ols_predict(train: pd.DataFrame, test: pd.Series, cols: list[str], target: str) -> float:
    X = np.column_stack([np.ones(len(train))] + [train[c].values for c in cols])
    y = train[target].values
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    return float(np.dot([1.0] + [test[c] for c in cols], beta))


# ------------------------------------------------------------------ baselines


def baseline_predict(name: str, train: pd.DataFrame, test: pd.Series, target: str) -> float:
    lag1 = "rev_yoy_lag1" if target == "rev_yoy" else "beat_lag1"
    lag2 = "rev_yoy_lag2" if target == "rev_yoy" else None

    if name == "AR(1)":
        return _ols_predict(train, test, [lag1], target)
    if name == "AR(1)+trend":
        return _ols_predict(train, test, [lag1, "trend"], target)
    if name == "random walk":
        return float(test[lag1])
    if name == "ARIMA(1,1,0)":
        # Model the change: d_t = c + phi * d_{t-1}, then y_t = y_{t-1} + d_t.
        if lag2 is None or train[lag2].isna().all():
            return float(test[lag1])
        d = train[lag1] - train[lag2]
        dy = train[target] - train[lag1]
        ok = d.notna() & dy.notna()
        if ok.sum() < 5:
            return float(test[lag1])
        X = np.column_stack([np.ones(ok.sum()), d[ok].values])
        beta = np.linalg.lstsq(X, dy[ok].values, rcond=None)[0]
        d_test = float(test[lag1] - test[lag2]) if pd.notna(test[lag2]) else 0.0
        return float(test[lag1] + beta[0] + beta[1] * d_test)
    if name == "guidance + trailing beat (8q)":
        # Same rule, but the mean beat is taken over the last 8 quarters only.
        # The expanding-window version is contaminated by the 2020-21 regime,
        # when beats ran to 12%; recent beats sit near 4.3%.
        # NOTE: the 8-quarter window is a POST HOC choice, made after seeing
        # that the full-sample mean is regime-contaminated. It is reported as a
        # baseline variant, not as a pre-registered specification, and it makes
        # the bar for the signals HIGHER, not lower.
        recent = train[target].tail(8) if target == "beat_vs_guide" else None
        if target == "beat_vs_guide":
            return float(recent.mean())
        mean_beat = train["beat_vs_guide"].tail(8).mean()
        implied = test["guide_implied_yoy"]
        if pd.isna(implied):
            return float(train[target].tail(8).mean())
        return float((1 + implied) * (1 + mean_beat) - 1)
    if name == "guidance + mean beat":
        if target == "beat_vs_guide":
            return float(train[target].mean())
        # rev_yoy: apply the historical mean beat to the guidance midpoint.
        mean_beat = train["beat_vs_guide"].mean()
        implied = test["guide_implied_yoy"]
        if pd.isna(implied):
            return float(train[target].mean())
        return float((1 + implied) * (1 + mean_beat) - 1)
    raise ValueError(name)


BASELINES = [
    "AR(1)",
    "AR(1)+trend",
    "random walk",
    "ARIMA(1,1,0)",
    "guidance + mean beat",
    "guidance + trailing beat (8q)",
]


# -------------------------------------------------------------- walk-forward


def walk_forward(f: pd.DataFrame, target: str, feature: str | None,
                 baseline: str = "AR(1)") -> dict | None:
    """Expanding window. Returns aligned prediction arrays for model and baseline.

    The model is always `feature + lag1`; the baseline is whichever of the
    baseline set is named. Both see the identical training rows, so the
    comparison is like for like.
    """
    lag1 = "rev_yoy_lag1" if target == "rev_yoy" else "beat_lag1"
    need = [target, lag1, "trend", "rev_yoy_lag2", "guide_implied_yoy", "beat_vs_guide"]
    if feature:
        need = need + [feature]
    d = f[["quarter"] + [c for c in dict.fromkeys(need) if c in f]].copy()
    d = d.dropna(subset=[target, lag1] + ([feature] if feature else [])).reset_index(drop=True)
    if len(d) < FIRST_TRAIN + 4:
        return None

    model_pred, base_pred, actual, prev, quarters = [], [], [], [], []
    for i in range(FIRST_TRAIN, len(d)):
        tr, te = d.iloc[:i], d.iloc[i]
        if feature:
            model_pred.append(_ols_predict(tr, te, [feature, lag1], target))
        base_pred.append(baseline_predict(baseline, tr, te, target))
        actual.append(te[target])
        prev.append(te[lag1])
        quarters.append(te["quarter"])

    return {
        "quarters": quarters,
        "actual": np.array(actual, dtype=float),
        "prev": np.array(prev, dtype=float),
        "model": np.array(model_pred, dtype=float) if feature else None,
        "base": np.array(base_pred, dtype=float),
    }


def metrics(pred: np.ndarray, actual: np.ndarray, prev: np.ndarray) -> dict:
    err = pred - actual
    with np.errstate(divide="ignore", invalid="ignore"):
        mape = np.mean(np.abs(err / actual)) * 100
    return {
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "mape_%": float(mape),
        "hit": float(np.mean(np.sign(pred - prev) == np.sign(actual - prev))),
    }


# ------------------------------------------------------- significance testing


def diebold_mariano(e1: np.ndarray, e2: np.ndarray, h: int = 1) -> tuple[float, float]:
    """DM test on squared-error differentials with the HLN small-sample fix.

    e1 = model errors, e2 = baseline errors. Negative statistic favours e1.
    Returns (HLN-corrected statistic, two-sided p-value from t_{n-1}).
    """
    d = e1**2 - e2**2
    n = len(d)
    d_bar = d.mean()
    gamma0 = np.sum((d - d_bar) ** 2) / n
    var_d = gamma0
    for lag in range(1, h):
        gamma = np.sum((d[lag:] - d_bar) * (d[:-lag] - d_bar)) / n
        var_d += 2 * gamma
    if var_d <= 0:
        return np.nan, np.nan
    dm = d_bar / np.sqrt(var_d / n)
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * correction
    p = 2 * (1 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return float(dm_hln), float(p)


def bootstrap_rmse_ratio(e1: np.ndarray, e2: np.ndarray, rng) -> tuple[float, float]:
    n = len(e1)
    ratios = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, n, n)
        r1 = np.sqrt(np.mean(e1[idx] ** 2))
        r2 = np.sqrt(np.mean(e2[idx] ** 2))
        if r2 > 0:
            ratios.append(r1 / r2)
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return float(lo), float(hi)


# --------------------------------------------------------------------- grids


def run_grid(f: pd.DataFrame, baseline: str = "AR(1)") -> pd.DataFrame:
    """All 24 candidate cells plus their 24 matched controls."""
    rows = []
    for target in TARGETS:
        for cand in CANDIDATES:
            for win in WINDOWS:
                for role, name in (("candidate", cand), ("control", CONTROLS[cand])):
                    feat = f"{name}_{win}"
                    if feat not in f:
                        continue
                    r = walk_forward(f, target, feat, baseline)
                    if r is None:
                        continue
                    m = metrics(r["model"], r["actual"], r["prev"])
                    b = metrics(r["base"], r["actual"], r["prev"])
                    rows.append(
                        {
                            "target": target,
                            "candidate": cand,
                            "window": win,
                            "role": role,
                            "feature": feat,
                            "n_oos": len(r["actual"]),
                            "rmse": m["rmse"],
                            "rmse_base": b["rmse"],
                            "rmse_ratio": m["rmse"] / b["rmse"],
                            "mape_%": m["mape_%"],
                            "hit": m["hit"],
                            "hit_base": b["hit"],
                        }
                    )
    return pd.DataFrame(rows)


def permutation_null(f: pd.DataFrame, mode: str, rng, baseline: str = "AR(1)",
                     opponents: dict | None = None) -> np.ndarray:
    """How many of the 24 candidate cells beat 0.9 by chance?

    mode='feature' permutes the feature values across quarters. This is the
    right null for "the feature carries no information": the target's
    autocorrelation and therefore the AR(1) baseline are left intact.

    mode='target' permutes the target series and rebuilds its own lag, as
    literally requested. It is reported too, but note it destroys the target's
    autocorrelation, which cripples the AR(1) baseline and therefore makes the
    ratio easier to beat for reasons unrelated to the feature.
    """
    counts = []
    for _ in range(N_PERM):
        g = f.copy()
        if mode == "feature":
            perm = rng.permutation(len(g))
            for cand in CANDIDATES:
                for win in WINDOWS:
                    col = f"{cand}_{win}"
                    if col in g:
                        g[col] = g[col].values[perm]
        else:
            for target in TARGETS:
                vals = g[target].values.copy()
                order = rng.permutation(len(vals))
                g[target] = vals[order]
            g["rev_yoy_lag1"] = g["rev_yoy"].shift(1)
            g["rev_yoy_lag2"] = g["rev_yoy"].shift(2)
            g["beat_lag1"] = g["beat_vs_guide"].shift(1)

        n_hits = 0
        for target in TARGETS:
            for cand in CANDIDATES:
                for win in WINDOWS:
                    feat = f"{cand}_{win}"
                    if feat not in g:
                        continue
                    opp = opponents[target] if opponents else baseline
                    r = walk_forward(g, target, feat, opp)
                    if r is None:
                        continue
                    ratio = metrics(r["model"], r["actual"], r["prev"])["rmse"] / metrics(
                        r["base"], r["actual"], r["prev"]
                    )["rmse"]
                    n_hits += ratio < 0.9
        counts.append(n_hits)
    return np.array(counts)


def main() -> None:
    rng = np.random.default_rng(SEED)
    f = frame()
    pd.set_option("display.width", 230)

    # ---------------- 1. baselines, on their own ----------------
    print("=" * 78)
    print("BASELINES (no alternative data), expanding walk-forward")
    print("=" * 78)
    rows = []
    for target in TARGETS:
        for b in BASELINES:
            r = walk_forward(f, target, None, b)
            if r is None:
                continue
            m = metrics(r["base"], r["actual"], r["prev"])
            rows.append({"target": target, "baseline": b, "n_oos": len(r["actual"]), **m})
    base_tbl = pd.DataFrame(rows)
    base_tbl.to_csv(sc.PROCESSED / "wf_baselines.csv", index=False)
    print(base_tbl.round(4).to_string(index=False))

    best = (
        base_tbl.sort_values("rmse").groupby("target").first()[["baseline", "rmse"]]
    )
    print("\nBest baseline per target:")
    print(best.to_string())
    print("\nNote: whichever baseline wins here is the opponent the signal must"
          "\nbeat. Reporting only against AR(1) would be picking a weak opponent.")

    # ---------------- 2. trend-only feature (D27) ----------------
    print("\n" + "=" * 78)
    print("TREND-ONLY FEATURE -- identical pipeline, contains no Datadog data")
    print("=" * 78)
    trend_rows = []
    for target in TARGETS:
        for b in ("AR(1)", best.loc[target, "baseline"]):
            r = walk_forward(f, target, "trend", b)
            if r is None:
                continue
            m = metrics(r["model"], r["actual"], r["prev"])
            mb = metrics(r["base"], r["actual"], r["prev"])
            dm, p = diebold_mariano(r["model"] - r["actual"], r["base"] - r["actual"])
            trend_rows.append(
                {
                    "target": target,
                    "vs_baseline": b,
                    "rmse_ratio": m["rmse"] / mb["rmse"],
                    "hit": m["hit"],
                    "dm_stat": dm,
                    "dm_p": p,
                }
            )
    trend_tbl = pd.DataFrame(trend_rows)
    print(trend_tbl.round(4).to_string(index=False))

    # ---------------- 3. the full grid (D26) ----------------
    print("\n" + "=" * 78)
    print("FULL GRID: 3 features x 4 windows x 2 targets, each with its control")
    print("=" * 78)
    grid = run_grid(f, "AR(1)")
    grid.to_csv(sc.PROCESSED / "wf_grid.csv", index=False)
    for target in TARGETS:
        piv = grid[(grid["target"] == target)].pivot_table(
            index=["candidate", "role"], columns="window", values="rmse_ratio"
        )[WINDOWS]
        print(f"\ntarget = {target}   (RMSE ratio vs AR(1); < 1 beats it)")
        print(piv.round(3).to_string())

    cands = grid[grid["role"] == "candidate"]
    n_below = int((cands["rmse_ratio"] < 0.9).sum())
    print(f"\nCandidate cells with RMSE ratio < 0.9: {n_below} of {len(cands)}")

    # ---- the decisive table: the same grid against the STRONGEST baseline ----
    opponents = {t_: best.loc[t_, "baseline"] for t_ in TARGETS}
    print("\n" + "=" * 78)
    print("SAME GRID vs the STRONGEST baseline per target -- the decisive table")
    print("=" * 78)
    grid_best = []
    for target in TARGETS:
        gb = run_grid(f[f.columns], opponents[target])
        gb = gb[gb["target"] == target]
        gb["vs_baseline"] = opponents[target]
        grid_best.append(gb)
    grid_best = pd.concat(grid_best, ignore_index=True)
    grid_best.to_csv(sc.PROCESSED / "wf_grid_best_baseline.csv", index=False)
    for target in TARGETS:
        piv = grid_best[grid_best["target"] == target].pivot_table(
            index=["candidate", "role"], columns="window", values="rmse_ratio"
        )[WINDOWS]
        print(f"\ntarget = {target}   vs {opponents[target]}   (< 1 beats it)")
        print(piv.round(3).to_string())
    cb = grid_best[grid_best["role"] == "candidate"]
    n_below_best = int((cb["rmse_ratio"] < 0.9).sum())
    n_beat_best = int((cb["rmse_ratio"] < 1.0).sum())
    print(f"\nCandidate cells beating the strongest baseline at all: "
          f"{n_beat_best} of {len(cb)}")
    print(f"Candidate cells with RMSE ratio < 0.9: {n_below_best} of {len(cb)}")

    # ---------------- 4. permutation null (D26) ----------------
    print("\n" + "=" * 78)
    print(f"PERMUTATION NULL, {N_PERM} draws -- how many cells beat 0.9 by chance?")
    print("=" * 78)
    perm_rows = []
    for mode, opp, obs in (
        ("feature", None, n_below),
        ("target", None, n_below),
        ("feature", opponents, n_below_best),
    ):
        label = f"permute {mode}" + (" (vs strongest baseline)" if opp else " (vs AR(1))")
        counts = permutation_null(f, mode, np.random.default_rng(SEED), opponents=opp)
        p_val = float(np.mean(counts >= obs))
        perm_rows.append(
            {
                "null": label,
                "mean_cells_below_0.9": counts.mean(),
                "median": float(np.median(counts)),
                "p95": float(np.percentile(counts, 95)),
                "max": int(counts.max()),
                "observed": obs,
                "p_value": p_val,
            }
        )
        print(f"  {label}: mean {counts.mean():.2f} cells, "
              f"95th pct {np.percentile(counts, 95):.0f}, max {counts.max()}, "
              f"observed {obs}, p = {p_val:.3f}")
    perm_tbl = pd.DataFrame(perm_rows)
    perm_tbl.to_csv(sc.PROCESSED / "wf_permutation_null.csv", index=False)

    # ---------------- 5. DM + bootstrap on the headline cells ----------------
    print("\n" + "=" * 78)
    print("SIGNIFICANCE: Diebold-Mariano (HLN) + bootstrap CI on the RMSE ratio")
    print("=" * 78)
    sig_rows = []
    for target in TARGETS:
        opponent = best.loc[target, "baseline"]
        for cand in CANDIDATES:
            for win in ("d45",):
                for role, name in (("candidate", cand), ("control", CONTROLS[cand])):
                    feat = f"{name}_{win}"
                    for b in dict.fromkeys(["AR(1)", opponent]):
                        r = walk_forward(f, target, feat, b)
                        if r is None:
                            continue
                        e1, e2 = r["model"] - r["actual"], r["base"] - r["actual"]
                        dm, p = diebold_mariano(e1, e2)
                        lo, hi = bootstrap_rmse_ratio(e1, e2, np.random.default_rng(SEED))
                        sig_rows.append(
                            {
                                "target": target,
                                "feature": feat,
                                "role": role,
                                "vs_baseline": b,
                                "rmse_ratio": np.sqrt(np.mean(e1**2)) / np.sqrt(np.mean(e2**2)),
                                "boot_ci_lo": lo,
                                "boot_ci_hi": hi,
                                "ci_covers_1": lo <= 1 <= hi,
                                "dm_stat": dm,
                                "dm_p": p,
                                "n_oos": len(e1),
                            }
                        )
    sig = pd.DataFrame(sig_rows)
    sig.to_csv(sc.PROCESSED / "wf_significance.csv", index=False)
    print(sig.round(4).to_string(index=False))
    print("\nA cell is only a result if the CI excludes 1.0 AND the DM p-value is"
          "\nsmall AND its matched control fails. Anything less is inconclusive.")


if __name__ == "__main__":
    main()
