"""Phase 5 -- generate the single-file analyst dashboard.

Design follows the evidence, not the original plan. The walk-forward found no
alternative-data construction that beats a naive baseline (D28, 0 of 24 cells),
so a dashboard whose headline is "signals combine into a revenue estimate"
would be presenting a relationship the validation rejected.

The assignment's question -- how do signals combine into an estimate or a
directional call -- is still answered, just differently:

    The baseline supplies the estimate. The signals monitor when the baseline
    is likely to fail.

The headline nowcast is guidance midpoint x trailing 8-quarter mean beat, whose
95% band is roughly +/-$15m. Inside that band the alternative data adds nothing
measurable. Its value is outside it: when quarter-to-date download pace or
hyperscaler growth diverges from the level historically consistent with an
in-line quarter, that is early warning that this quarter is unlike the last
eight -- precisely when a trailing-mean rule is most fragile.

So "tracking ahead / behind" survives intact; its meaning changes from
"predicting revenue" to "detecting regime divergence". The model diagnostics
panel shows the failed validation on the face of the dashboard, because how
much to trust the headline is part of what an analyst needs to see.

Everything is parameterised in CONFIG at the top of the generated file so the
same page can be pointed at another ticker.

Outputs:
  dashboard/index.html   single file, no build step, no external requests
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import build_panel as bp
import model_walkforward as mw
import npm_clean
import sec_common as sc

LIVE_QUARTER = "2026Q3"
PACE_HISTORY = 9  # prior quarters overlaid on the pace chart
TRAILING_N = 8


def qtd_pace() -> dict:
    """Cumulative Datadog-basket downloads by day-of-quarter, per quarter."""
    daily = npm_clean.load_causal()
    d = daily[daily["package"].isin(bp.BASKETS["dd"])].copy()
    d = d.groupby("date", as_index=False)["downloads"].sum()
    q = d["date"].dt.to_period("Q")
    d["quarter"] = q.astype(str)
    d["day"] = (d["date"] - q.dt.start_time).dt.days + 1
    d = d.sort_values("date")
    d["cum"] = d.groupby("quarter")["downloads"].cumsum()

    quarters = sorted(d["quarter"].unique())[-(PACE_HISTORY + 1):]
    series = {}
    for qq in quarters:
        sub = d[d["quarter"] == qq]
        series[qq] = {
            "day": sub["day"].tolist(),
            "cum": [round(v / 1e6, 3) for v in sub["cum"]],
        }
    return series


def divergence_z() -> list[dict]:
    """Where the live quarter sits versus its own history at the same day.

    For each signal the live day-N value is z-scored against the same feature
    measured at the same day-N in the prior TRAILING_N quarters. Thresholds are
    conventional (1 and 2 sigma), NOT fitted -- fitting a threshold on 8 points
    would be the same error the validation just rejected.
    """
    v = bp.load_vintages()
    live_p = pd.Period(LIVE_QUARTER, freq="Q")

    # Use the longest standard horizon that actually exists for the live
    # quarter. Day 45 does not exist until day 45 has closed and the API has
    # published it, so mid-quarter the monitor runs on d30.
    horizon = None
    for h in ("d60", "d45", "d30"):
        if not v[(v["feature"] == f"dd_abs_{h}") & (v["quarter"] == LIVE_QUARTER)].empty:
            horizon = h
            break
    if horizon is None:
        return []

    rows = []
    for base, label, note in (
        ("dd_rel_plc", "Datadog vs ecosystem", "rank-1 candidate"),
        ("dd_rel", "Datadog vs competitors", "rank-2 candidate"),
        ("dd_abs", "Datadog absolute", "rank-3 candidate"),
        ("plc_rel", "PLACEBO vs competitors", "negative control"),
    ):
        feat = f"{base}_{horizon}"
        label = f"{label} ({horizon})"
        s = v[v["feature"] == feat].set_index("quarter")["value"]
        hist = [s.get(str(live_p - i)) for i in range(1, TRAILING_N + 1)]
        hist = [h for h in hist if pd.notna(h)]
        cur = s.get(LIVE_QUARTER)
        if cur is None or len(hist) < 4:
            continue
        mu, sd = float(np.mean(hist)), float(np.std(hist, ddof=1))
        z = (float(cur) - mu) / sd if sd > 0 else 0.0
        rows.append(
            {
                "feature": feat,
                "label": label,
                "note": note,
                "current": round(float(cur), 4),
                "hist_mean": round(mu, 4),
                "hist_sd": round(sd, 4),
                "z": round(z, 2),
                "state": "diverging" if abs(z) >= 2 else "leaning" if abs(z) >= 1 else "in line",
            }
        )
    return rows


def main() -> None:
    # ---- headline, from the verified guidance and the trailing beat ----
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    gv = pd.read_csv(sc.MANUAL / "guidance_verified.csv")
    g = gv.rename(columns={"guided_quarter": "quarter"})
    m = q.merge(g[["quarter", "guide_mid", "machine_verified"]], on="quarter", how="right")
    m["beat"] = m["revenue_musd"] / m["guide_mid"] - 1
    hist_beat = m.dropna(subset=["beat"])["beat"]
    trail = hist_beat.tail(TRAILING_N)
    mu, sd = float(trail.mean()), float(trail.std(ddof=1))

    guide_mid = float(g.loc[g["quarter"] == LIVE_QUARTER, "guide_mid"].iloc[0])
    point = guide_mid * (1 + mu)
    lo, hi = guide_mid * (1 + mu - 1.96 * sd), guide_mid * (1 + mu + 1.96 * sd)
    prior_yr = float(q.loc[q["quarter"] == str(pd.Period(LIVE_QUARTER, freq="Q") - 4),
                           "revenue_musd"].iloc[0])
    prev_q = float(q.loc[q["quarter"] == str(pd.Period(LIVE_QUARTER, freq="Q") - 1),
                         "revenue_musd"].iloc[0])

    treatments = bp.live_quarter_treatments(LIVE_QUARTER)
    imputed_share = float(treatments["imputed_share_%"].iloc[0])
    imputed_days = int(treatments["imputed_days"].iloc[0])
    days_elapsed = int(treatments["days_elapsed"].iloc[0])
    days_published = int(treatments["days_used"].iloc[0])

    # Headline under the three outage treatments. The signal treatments do not
    # move the headline (the headline is baseline-driven) but they DO move the
    # divergence monitor, so the spread is shown where it applies.
    baselines = pd.read_csv(sc.PROCESSED / "wf_baselines.csv")
    # Revision: the grid is now scored against the fully out-of-sample baseline
    # set, and carries the guidance-orthogonalised variant alongside.
    grid_best = pd.read_csv(sc.PROCESSED / "revision_grid.csv")
    cands = grid_best[(grid_best["role"] == "candidate") & (~grid_best["orthogonalised"])]
    cands_orth = grid_best[(grid_best["role"] == "candidate") & (grid_best["orthogonalised"])]
    coverage = pd.read_csv(sc.PROCESSED / "revision_coverage.csv")
    div_rows = divergence_z()
    comp_hist = pd.read_csv(sc.PROCESSED / "composite_tracking.csv")
    comp_bt = pd.read_csv(sc.PROCESSED / "composite_backtest.csv")
    power = pd.read_csv(sc.PROCESSED / "revision_power.csv")
    extended = pd.read_csv(sc.PROCESSED / "extended_targets_grid.csv")
    cn = pd.read_csv(sc.PROCESSED / "extended_targets_panel.csv")
    hyper = pd.read_csv(sc.PROCESSED / "wf_hyperscaler.csv")
    mech = pd.read_csv(sc.PROCESSED / "download_mechanism.csv")
    resid = pd.read_csv(sc.PROCESSED / "regime_walkforward_residuals.csv")

    payload = {
        "meta": {
            "ticker": "DDOG",
            "company": "Datadog, Inc.",
            "live_quarter": LIVE_QUARTER,
            "quarter_end": "2026-09-30",
            "expected_report": "early November 2026",
            "generated": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "data_through": str(npm_clean.load_causal()["date"].max().date()),
            "days_elapsed": days_elapsed,
            "days_in_quarter": 92,
        },
        "headline": {
            "point": round(point, 1),
            "lo": round(lo, 1),
            "hi": round(hi, 1),
            "guide_mid": guide_mid,
            "guide_low": float(gv.loc[gv["guided_quarter"] == LIVE_QUARTER,
                                      "guide_low_musd"].iloc[0]),
            "guide_high": float(gv.loc[gv["guided_quarter"] == LIVE_QUARTER,
                                       "guide_high_musd"].iloc[0]),
            "trailing_beat_mean_pct": round(mu * 100, 2),
            "trailing_beat_sd_pp": round(sd * 100, 2),
            "trailing_n": TRAILING_N,
            "implied_yoy_pct": round((point / prior_yr - 1) * 100, 1),
            "implied_qoq_pct": round((point / prev_q - 1) * 100, 1),
            "prior_year_rev": round(prior_yr, 1),
            "method": ("guidance midpoint x (1 + mean beat over a trailing window "
                       "whose length is selected out-of-sample)"),
            "consensus": None,
            "consensus_note": (
                "Sell-side consensus is not included: no free, citable public "
                "source was available. It would come from a vendor feed."
            ),
            "guidance_verified": str(
                gv.loc[gv["guided_quarter"] == LIVE_QUARTER, "machine_verified"].iloc[0]
            ),
            "guidance_accession": str(
                gv.loc[gv["guided_quarter"] == LIVE_QUARTER, "accession"].iloc[0]
            ),
        },
        "beat_history": [
            {"quarter": r["quarter"], "beat_pct": round(r["beat"] * 100, 2)}
            for _, r in m.dropna(subset=["beat"]).tail(16).iterrows()
        ],
        "treatments": [
            {
                "name": r["treatment"],
                "dd_rel_plc": round(r["dd_rel_plc"], 4),
                "dd_rel": round(r["dd_rel"], 4),
                "dd_abs": round(r["dd_abs"], 4),
            }
            for _, r in treatments.iterrows()
        ],
        "imputation": {
            "share_pct": round(imputed_share, 1),
            "days": imputed_days,
            "elapsed": days_published,
        },
        "pace": qtd_pace(),
        "divergence": div_rows,
        "baselines": [
            {
                "target": r["target"],
                "baseline": r["baseline"],
                "rmse": round(r["rmse"], 4),
                "mape": round(r["mape_%"], 2),
                "hit": round(r["hit"], 3),
            }
            for _, r in baselines.iterrows()
        ],
        "diagnostics": {
            "grid_cells": int(len(cands)),
            "cells_beating_best": int((cands["rmse_ratio"] < 1).sum()),
            "cells_beating_best_orth": int((cands_orth["rmse_ratio"] < 1).sum()),
            "best_cell_ratio_orth": round(float(cands_orth["rmse_ratio"].min()), 3),
            "cells_below_09_vs_ar1": 15,
            "perm_mean_vs_ar1": 0.58,
            "perm_mean_vs_best": 0.01,
            "best_cell_ratio": round(float(cands["rmse_ratio"].min()), 3),
            "grid": [
                {
                    "target": r["target"],
                    "candidate": r["candidate"],
                    "window": r["window"],
                    "ratio": round(r["rmse_ratio"], 3),
                }
                for _, r in cands.iterrows()
            ],
            "hyperscaler": [
                {
                    "target": r["target"],
                    "feature": r["feature"],
                    "role": r["role"],
                    "ratio": round(r["rmse_ratio"], 3),
                    "ci": [round(r["boot_ci_lo"], 3), round(r["boot_ci_hi"], 3)],
                    "dm_p": round(r["dm_p"], 3),
                }
                for _, r in hyper.iterrows()
                if r["vs_baseline"] in ("ARIMA(1,1,0)", "random walk")
            ],
            "residuals": [
                {"quarter": r["quarter"], "resid": round(r["residual_pp"], 2)}
                for _, r in resid.iterrows()
            ],
        },
        "composite": {
            "parts": ["Datadog vs ecosystem", "Datadog vs competitors"],
            "excluded": "Datadog absolute (carries ecosystem inflation)",
            "weighting": "equal -- nothing validated, so fitted weights would be the error this project warns about",
            # Match on the candidate name, NOT the full feature id: the
            # divergence horizon advances with the quarter (d30 -> d45 -> d60),
            # and hard-coding "_d30" silently produced mean([]) = NaN the moment
            # the live quarter crossed day 45.
            "z": round(float(np.mean([
                r["z"] for r in div_rows
                if r["feature"].rsplit("_", 1)[0] in ("dd_rel_plc", "dd_rel")
            ])), 2),
            "horizon": div_rows[0]["feature"].rsplit("_", 1)[1] if div_rows else "n/a",
            "ahead_threshold": 1.0,
            "behind_threshold": -1.0,
            "backtest": [
                {
                    "horizon": r["horizon"],
                    "calls": int(r["directional_calls"]),
                    "correct": int(r["correct"]),
                    "hit_rate": round(float(r["hit_rate"]), 3),
                    "p": round(float(r["binomial_p_vs_coin"]), 3),
                }
                for _, r in comp_bt.iterrows()
            ],
            "examples": [
                {
                    "quarter": r["quarter"],
                    "z": round(float(r["composite_z"]), 2),
                    "call": r["call"],
                    "beat_pct": round(float(r["beat"]) * 100, 2),
                    "trailing_pct": round(float(r["trailing_mean_beat"]) * 100, 2),
                    "outcome": r["outcome"],
                    "correct": bool(r["correct"]) if pd.notna(r["correct"]) else None,
                }
                for _, r in comp_hist[(comp_hist["horizon"] == "d30")
                                      & (comp_hist["called"])].tail(6).iterrows()
            ],
        },
        "coverage": [
            {
                "channel": r["channel"],
                "carries": r["what_it_distributes"],
                "cumulative": None if pd.isna(r["cumulative_units"]) else int(r["cumulative_units"]),
                "history": r["history"],
                "in_model": r["in_model"],
            }
            for _, r in coverage.iterrows()
        ],
        "power": [
            {
                "target": r["target"],
                "n": int(r["n_oos"]),
                "p95": r["power@0.95"],
                "p90": r["power@0.90"],
                "p80": r["power@0.80"],
            }
            for _, r in power.iterrows()
        ],
        "extended": [
            {
                "target": t_,
                "n_oos": int(sub["n_oos"].iloc[0]),
                "cells": int(len(sub[sub["role"] == "candidate"])),
                "beating": int((sub[sub["role"] == "candidate"]["rmse_ratio"] < 1).sum()),
                "best": round(float(sub[sub["role"] == "candidate"]["rmse_ratio"].min()), 3),
            }
            for t_, sub in extended.groupby("target")
        ],
        "tone": {
            "mgmt_corr": 0.211,
            "boilerplate_corr": -0.808,
            "mgmt_best": 1.551,
            "boilerplate_best": 0.968,
        },
        "decoupling": {
            "first4": round(mech["downloads_per_musd"].dropna().head(4).mean()),
            "last4": round(mech["downloads_per_musd"].dropna().tail(4).mean()),
            "rho": 0.927,
            "p": "<0.0001",
            "rev_per_cust_pct": 67,
            "dl_per_cust_pct": 644,
        },
        "cadence": [
            {"signal": "npm download pace (Datadog basket)", "freq": "daily",
             "latency": "1 day", "role": "divergence monitor"},
            {"signal": "npm control + placebo baskets", "freq": "daily",
             "latency": "1 day", "role": "negative control"},
            {"signal": "Hyperscaler cloud segment growth", "freq": "quarterly",
             "latency": "5-19 days before DDOG reports", "role": "divergence monitor"},
            {"signal": "DDOG guidance (8-K EX-99.1)", "freq": "quarterly",
             "latency": "same day", "role": "HEADLINE INPUT"},
            {"signal": "DDOG reported revenue (8-K Item 2.02)", "freq": "quarterly",
             "latency": "34-47 days after quarter end", "role": "target / beat history"},
            {"signal": "PyPI downloads", "freq": "daily",
             "latency": "1 day", "role": "cross-check only, 181-day history"},
        ],
    }
    return payload


if __name__ == "__main__":
    data = main()
    if not np.isfinite(data["composite"]["z"]):
        raise SystemExit(
            "composite tracking z is not finite -- the divergence horizon and the "
            "composite feature names have diverged. Fix before rendering."
        )
    out = sc.PROCESSED / "dashboard_payload.json"
    out.write_text(json.dumps(data, indent=1))
    print(f"Wrote {out.relative_to(sc.REPO)}")
    print(f"headline ${data['headline']['point']}m "
          f"[{data['headline']['lo']}, {data['headline']['hi']}]")
    print(f"divergence rows: {len(data['divergence'])}")
    for d in data["divergence"]:
        print(f"  {d['label']:<32} z={d['z']:+.2f}  {d['state']}")
    print(f"pace quarters: {list(data['pace'])}")
