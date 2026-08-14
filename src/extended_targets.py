"""Critique 6 -- the assignment's other target metrics.

The Objective names "quarterly revenue and revenue growth, billings / RPO, net
revenue retention (NRR), or growth in large customers (ARR >= $100k)". The
first report modelled only revenue and revenue growth. This adds the rest.

This is not merely a coverage fix. It tests an economically motivated
hypothesis that the first pass listed as a known bias and then never acted on:

    Downloads are an UNWEIGHTED COUNT. Revenue is DOLLAR-WEIGHTED.
    One enterprise and one hobbyist contribute one download each, but
    contribute wildly different revenue.

If that mismatch is what breaks the mapping, then a count-type target --
the number of customers with ARR >= $100k -- should be the better match, and
the download signal should do relatively better against it than against
revenue. That is a falsifiable prediction, and it is tested here.

Targets added:
  cust_yoy      YoY growth in $100k+ ARR customers      28 quarters, press release
  rpo_yoy       YoY growth in remaining performance obligation   20 quarters, XBRL
  billings_yoy  YoY growth in derived billings          26 quarters
                billings = revenue + change in total deferred revenue

NRR is NOT included: Datadog discloses it qualitatively on earnings calls, not
as a number in the 8-K exhibits, and no citable public numeric series exists
within this project's data scope. Stated rather than approximated.

Outputs:
  processed/extended_targets_panel.csv
  processed/extended_targets_grid.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import model_walkforward as mw
import sec_common as sc

EXTRA_TARGETS = ["cust_yoy", "rpo_yoy", "billings_yoy"]


def extended_frame() -> pd.DataFrame:
    f = mw.frame()
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    cust = pd.read_csv(sc.MANUAL / "customers_100k_template.csv").rename(
        columns={"reported_quarter": "quarter"}
    )
    q = q.merge(cust[["quarter", "customers_ge_100k"]], on="quarter", how="left")

    per = pd.PeriodIndex(q["quarter"], freq="Q")
    full = pd.period_range(per.min(), per.max(), freq="Q")

    def yoy(col: str) -> np.ndarray:
        s = pd.Series(q[col].values, index=per).reindex(full)
        return (s / s.shift(4) - 1).reindex(per).values

    q["deferred_total"] = q["deferred_rev_current"].fillna(0) + q[
        "deferred_rev_noncurrent"
    ].fillna(0)
    q.loc[q["deferred_rev_current"].isna(), "deferred_total"] = np.nan
    d = pd.Series(q["deferred_total"].values, index=per).reindex(full)
    rev = pd.Series(q["revenue_musd"].values * 1e6, index=per).reindex(full)
    billings = rev + d.diff()
    q["billings_musd"] = (billings / 1e6).reindex(per).values

    q["cust_yoy"] = yoy("customers_ge_100k")
    q["rpo_yoy"] = yoy("rpo_total")
    b = pd.Series(q["billings_musd"].values, index=per).reindex(full)
    q["billings_yoy"] = (b / b.shift(4) - 1).reindex(per).values

    keep = ["quarter", "cust_yoy", "rpo_yoy", "billings_yoy", "customers_ge_100k",
            "billings_musd", "rpo_total"]
    out = f.merge(q[keep], on="quarter", how="left")
    for t in EXTRA_TARGETS:
        out[f"{t}_lag1"] = out[t].shift(1)
        out[f"{t}_lag2"] = out[t].shift(2)
    return out


def wf(f: pd.DataFrame, target: str, feature: str | None, baseline: str) -> dict | None:
    """Walk-forward for the extra targets, reusing the Phase 4 machinery."""
    lag1, lag2 = f"{target}_lag1", f"{target}_lag2"
    cols = ["quarter", target, lag1, lag2, "trend"]
    if feature:
        cols.append(feature)
    d = f[[c for c in dict.fromkeys(cols) if c in f]].copy()
    d = d.dropna(subset=[target, lag1] + ([feature] if feature else [])).reset_index(drop=True)
    if len(d) < mw.FIRST_TRAIN + 4:
        return None

    model_pred, base_pred, actual, prev, quarters = [], [], [], [], []
    for i in range(mw.FIRST_TRAIN, len(d)):
        tr, te = d.iloc[:i], d.iloc[i]
        if feature:
            model_pred.append(mw._ols_predict(tr, te, [feature, lag1], target))
        if baseline == "AR(1)":
            base_pred.append(mw._ols_predict(tr, te, [lag1], target))
        elif baseline == "random walk":
            base_pred.append(float(te[lag1]))
        elif baseline == "AR(1)+trend":
            base_pred.append(mw._ols_predict(tr, te, [lag1, "trend"], target))
        elif baseline == "ARIMA(1,1,0)":
            dd = tr[lag1] - tr[lag2]
            dy = tr[target] - tr[lag1]
            ok = dd.notna() & dy.notna()
            if ok.sum() < 5:
                base_pred.append(float(te[lag1]))
            else:
                X = np.column_stack([np.ones(ok.sum()), dd[ok].values])
                beta = np.linalg.lstsq(X, dy[ok].values, rcond=None)[0]
                dt = float(te[lag1] - te[lag2]) if pd.notna(te[lag2]) else 0.0
                base_pred.append(float(te[lag1] + beta[0] + beta[1] * dt))
        else:
            raise ValueError(baseline)
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


def main() -> None:
    pd.set_option("display.width", 235)
    f = extended_frame()
    f[["quarter", "rev_yoy", "cust_yoy", "rpo_yoy", "billings_yoy"]].to_csv(
        sc.PROCESSED / "extended_targets_panel.csv", index=False
    )

    print("=" * 78)
    print("THE ASSIGNMENT'S OTHER TARGET METRICS")
    print("=" * 78)
    print(f[["quarter", "rev_yoy", "cust_yoy", "rpo_yoy", "billings_yoy"]]
          .dropna(subset=["cust_yoy"]).tail(10).round(4).to_string(index=False))
    print("\nNRR: not disclosed as a number in the 8-K exhibits. Excluded rather "
          "than approximated.")

    # ---- baselines per target ----
    print("\n" + "=" * 78)
    print("BASELINES PER TARGET")
    print("=" * 78)
    base_rows = []
    for target in EXTRA_TARGETS:
        for b in ("AR(1)", "AR(1)+trend", "random walk", "ARIMA(1,1,0)"):
            r = wf(f, target, None, b)
            if r is None:
                continue
            m = mw.metrics(r["base"], r["actual"], r["prev"])
            base_rows.append({"target": target, "baseline": b, "n_oos": len(r["actual"]), **m})
    bt = pd.DataFrame(base_rows)
    print(bt.round(4).to_string(index=False))
    best = bt.sort_values("rmse").groupby("target").first()["baseline"].to_dict()
    print("\nStrongest baseline per target:", best)

    # ---- grid ----
    print("\n" + "=" * 78)
    print("SIGNAL GRID ON THE OTHER TARGETS  (RMSE ratio vs strongest baseline)")
    print("=" * 78)
    rows = []
    for target in EXTRA_TARGETS:
        if target not in best:
            continue
        for cand in mw.CANDIDATES:
            for win in mw.WINDOWS:
                for role, name in (("candidate", cand), ("control", mw.CONTROLS[cand])):
                    feat = f"{name}_{win}"
                    if feat not in f:
                        continue
                    r = wf(f, target, feat, best[target])
                    if r is None:
                        continue
                    m = mw.metrics(r["model"], r["actual"], r["prev"])
                    mb = mw.metrics(r["base"], r["actual"], r["prev"])
                    e1, e2 = r["model"] - r["actual"], r["base"] - r["actual"]
                    dm, p = mw.diebold_mariano(e1, e2)
                    lo, hi = mw.bootstrap_rmse_ratio(e1, e2, np.random.default_rng(mw.SEED))
                    rows.append({
                        "target": target, "candidate": cand, "window": win, "role": role,
                        "n_oos": len(e1), "rmse_ratio": m["rmse"] / mb["rmse"],
                        "boot_lo": lo, "boot_hi": hi, "ci_covers_1": lo <= 1 <= hi,
                        "dm_p": p, "hit": m["hit"], "hit_base": mb["hit"],
                    })
    grid = pd.DataFrame(rows)
    grid.to_csv(sc.PROCESSED / "extended_targets_grid.csv", index=False)

    for target in EXTRA_TARGETS:
        sub = grid[grid["target"] == target]
        if sub.empty:
            print(f"\ntarget = {target}: insufficient history for walk-forward")
            continue
        piv = sub.pivot_table(index=["candidate", "role"], columns="window",
                              values="rmse_ratio")
        print(f"\ntarget = {target}   vs {best[target]}   n_oos={sub['n_oos'].iloc[0]}")
        print(piv.round(3).to_string())
        cands = sub[sub["role"] == "candidate"]
        n_beat = int((cands["rmse_ratio"] < 1).sum())
        print(f"  candidate cells beating the baseline: {n_beat} of {len(cands)}"
              f"   best {cands['rmse_ratio'].min():.3f}")
        wins = cands[cands["rmse_ratio"] < 1].sort_values("rmse_ratio")
        for _, w in wins.head(4).iterrows():
            ctrl = sub[(sub["role"] == "control") & (sub["window"] == w["window"])
                       & (sub["candidate"] == w["candidate"])]
            cr = ctrl["rmse_ratio"].iloc[0] if len(ctrl) else np.nan
            print(f"    {w['candidate']}_{w['window']}: ratio {w['rmse_ratio']:.3f} "
                  f"CI [{w['boot_lo']:.2f}, {w['boot_hi']:.2f}] DM p={w['dm_p']:.3f} "
                  f"| matched control {cr:.3f} "
                  f"{'(control ALSO beats -> not attributable)' if cr < 1 else '(control fails -> attributable)'}")

    print("\n" + "=" * 78)
    print("THE COUNT-VS-DOLLARS TEST")
    print("=" * 78)
    rev_grid = pd.read_csv(sc.PROCESSED / "revision_grid.csv")
    rev_best = rev_grid[(~rev_grid["orthogonalised"]) & (rev_grid["role"] == "candidate")
                        & (rev_grid["target"] == "rev_yoy")]["rmse_ratio"].min()
    cg = grid[(grid["target"] == "cust_yoy") & (grid["role"] == "candidate")]
    if not cg.empty:
        print(f"  best cell vs revenue growth (dollar-weighted): {rev_best:.3f}")
        print(f"  best cell vs customer growth (count-type):     {cg['rmse_ratio'].min():.3f}")
        print("\n  Prediction under the count-vs-dollars hypothesis: downloads, being")
        print("  an unweighted count, should track a count target better than a")
        print("  dollar-weighted one. Compare the two numbers above.")


if __name__ == "__main__":
    main()
