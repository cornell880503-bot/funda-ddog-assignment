"""The composite tracking indicator, and a backtest of the directional call.

Assignment Part 3 asks the dashboard to convey (a) how the signals combine into
a revenue estimate or a directional call, and (b) what "tracking ahead" versus
"tracking behind" looks like in the data. The first version of the dashboard
showed four individual z-scores and a magnitude label (in line / leaning /
diverging), which answers neither: a magnitude says nothing about direction,
and four separate scores are not a combination.

Construction, and why this one.

  composite_z = mean of the z-scores of the two DRIFT-ADJUSTED candidates
                (dd_rel_plc = Datadog vs ecosystem, dd_rel = Datadog vs
                competitors), each z-scored against its own value at the SAME
                day of quarter across the prior 8 quarters.

`dd_abs` is deliberately excluded from the composite: it carries the ecosystem
inflation that §4 of the report shows dominates the raw series, and including
it would make the indicator fire on registry-wide activity. It is still shown
on the dashboard, as is the placebo, so the analyst can see the contamination
directly.

Weights are equal. The report's own argument is that weights should come from
validation, and nothing here survived validation, so fitting weights would be
exactly the error the project exists to warn about. Equal weighting is the
honest default and is labelled as such.

Direction and thresholds: composite_z >= +1 is "tracking ahead", <= -1 is
"tracking behind", otherwise "in line". Conventional 1-sigma cut-offs, not
fitted.

**The backtest is the point.** A directional label is decoration unless someone
has checked whether it was right. For each historical quarter this computes the
call as of day 30/45/60 using only prior quarters, then asks whether the
quarter actually landed above or below its own trailing-8 mean beat. The hit
rate is reported with a binomial p-value against a coin flip -- including when
it is unimpressive, which is the expected outcome given everything else in this
project.

Outputs:
  processed/composite_tracking.csv    per-quarter call and outcome
  processed/composite_backtest.csv    hit rates by horizon
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

import build_panel as bp
import sec_common as sc

COMPOSITE_PARTS = ["dd_rel_plc", "dd_rel"]  # drift-adjusted only
SHOWN_ALSO = ["dd_abs", "plc_rel"]  # displayed for contamination context
LOOKBACK = 8  # quarters used for the z-score reference
AHEAD, BEHIND = 1.0, -1.0  # conventional 1-sigma, not fitted


def z_history(vint: pd.DataFrame, feature: str, horizon: str) -> pd.DataFrame:
    """z of `feature_horizon` for each quarter vs the prior LOOKBACK quarters."""
    col = f"{feature}_{horizon}"
    s = (
        vint[vint["feature"] == col]
        .set_index("quarter")["value"]
        .sort_index()
    )
    rows = []
    for i, (q, v) in enumerate(s.items()):
        prior = s.iloc[max(0, i - LOOKBACK) : i]
        if len(prior) < 4:
            continue
        sd = prior.std(ddof=1)
        rows.append(
            {
                "quarter": q,
                "feature": feature,
                "value": v,
                "hist_mean": prior.mean(),
                "hist_sd": sd,
                "z": (v - prior.mean()) / sd if sd and sd > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def label(z: float) -> str:
    if pd.isna(z):
        return "n/a"
    if z >= AHEAD:
        return "tracking ahead"
    if z <= BEHIND:
        return "tracking behind"
    return "in line"


def build(horizon: str = "d30") -> pd.DataFrame:
    vint = bp.load_vintages()
    parts = [z_history(vint, f, horizon) for f in COMPOSITE_PARTS]
    zs = (
        pd.concat(parts)
        .pivot(index="quarter", columns="feature", values="z")
        .dropna()
    )
    zs["composite_z"] = zs[COMPOSITE_PARTS].mean(axis=1)
    zs["call"] = zs["composite_z"].map(label)

    # Outcome: did the quarter beat by MORE than its own trailing-8 mean beat?
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    g = pd.read_csv(sc.MANUAL / "guidance_template.csv").rename(
        columns={"guided_quarter": "quarter"}
    )
    m = q.merge(g[["quarter", "guide_low_musd", "guide_high_musd"]], on="quarter", how="left")
    m["guide_mid"] = (m["guide_low_musd"] + m["guide_high_musd"]) / 2
    m["beat"] = m["revenue_musd"] / m["guide_mid"] - 1
    m = m[m["known_from_reliable"]].set_index("quarter")["beat"].dropna()
    trailing = m.shift(1).rolling(LOOKBACK, min_periods=4).mean()

    out = zs.join(m.rename("beat")).join(trailing.rename("trailing_mean_beat"))
    out = out.dropna(subset=["beat", "trailing_mean_beat"])
    out["outcome"] = np.where(
        out["beat"] > out["trailing_mean_beat"], "above trend", "below trend"
    )
    out["called"] = out["call"] != "in line"
    out["correct"] = np.where(
        out["call"] == "tracking ahead",
        out["outcome"] == "above trend",
        np.where(out["call"] == "tracking behind", out["outcome"] == "below trend", np.nan),
    )
    return out.reset_index()


def main() -> None:
    pd.set_option("display.width", 220)
    frames, summary = {}, []
    for horizon in ("d30", "d45", "d60"):
        df = build(horizon)
        df["horizon"] = horizon
        frames[horizon] = df
        called = df[df["called"]]
        n = len(called)
        hits = int(called["correct"].sum()) if n else 0
        p = stats.binomtest(hits, n, 0.5).pvalue if n else np.nan
        summary.append(
            {
                "horizon": horizon,
                "quarters_scored": len(df),
                "directional_calls": n,
                "correct": hits,
                "hit_rate": hits / n if n else np.nan,
                "binomial_p_vs_coin": p,
            }
        )

    allq = pd.concat(frames.values(), ignore_index=True)
    allq.to_csv(sc.PROCESSED / "composite_tracking.csv", index=False)
    summ = pd.DataFrame(summary)
    summ.to_csv(sc.PROCESSED / "composite_backtest.csv", index=False)

    print("=" * 78)
    print("COMPOSITE TRACKING INDICATOR")
    print("=" * 78)
    print(f"composite_z = mean z of {COMPOSITE_PARTS}, equal weight, "
          f"vs the same day-of-quarter across the prior {LOOKBACK} quarters")
    print(f"thresholds: >= +{AHEAD} tracking ahead, <= {BEHIND} tracking behind, "
          "else in line (conventional 1-sigma, not fitted)\n")

    d30 = frames["d30"]
    print("Day-30 call vs what the quarter actually did:")
    print(
        d30[["quarter", "dd_rel_plc", "dd_rel", "composite_z", "call",
             "beat", "trailing_mean_beat", "outcome", "correct"]]
        .round(3).to_string(index=False)
    )

    print("\n" + "=" * 78)
    print("DOES THE DIRECTIONAL CALL WORK?")
    print("=" * 78)
    print(summ.round(3).to_string(index=False))
    best = summ.iloc[summ["hit_rate"].idxmax()] if summ["hit_rate"].notna().any() else None
    if best is not None:
        print(f"\n  Best horizon {best['horizon']}: {int(best['correct'])}/"
              f"{int(best['directional_calls'])} correct "
              f"({best['hit_rate']:.0%}), binomial p={best['binomial_p_vs_coin']:.3f} "
              "against a coin flip.")
    print("\n  Read this the same way as everything else in the project: with this")
    print("  few directional calls, a hit rate is not distinguishable from chance")
    print("  unless the p-value says so. The indicator is a monitoring aid whose")
    print("  measured reliability is stated, not a validated forecast.")


if __name__ == "__main__":
    main()
