"""Phase 1 sanity checks and overview figure.

This is deliberately descriptive: it looks at the raw shape of the target and
the signal before any modelling. Nothing here is a result -- the contemporaneous
correlation printed at the end is a smell test, not evidence, because it uses
the full quarter of signal including days after the quarter closed.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import npm_clean
import sec_common as sc

FIG = sc.REPO / "report" / "figures"


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv", parse_dates=["end", "earnings_date"])
    npm = npm_clean.load_clean()  # registry-wide bad days imputed, express dropped

    rel = q[q["known_from_reliable"]]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))

    # (a) revenue growth, with the 2026 acceleration visible
    ax = axes[0, 0]
    m = q.dropna(subset=["rev_yoy"])
    ax.plot(m["end"], m["rev_yoy"] * 100, marker="o", ms=3)
    ax.axhline(0, lw=0.5, color="grey")
    ax.set_title("DDOG revenue growth, YoY % (first print)")
    ax.set_ylabel("%")

    # (b) how long after quarter close the number becomes public
    ax = axes[0, 1]
    ax.hist(rel["report_lag_days_known"], bins=range(32, 50), edgecolor="white")
    ax.set_title("Days from quarter end to earnings release (n=%d)" % len(rel))
    ax.set_xlabel("days")

    # (c) Datadog vs control npm volume, indexed to 2019-01
    ax = axes[1, 0]
    daily = (
        npm.groupby(["cohort", "date"], as_index=False)["downloads"]
        .sum()
        .pivot(index="date", columns="cohort", values="downloads")
        .rolling(28)
        .mean()
        .dropna()
    )
    base = daily.loc["2019-01-01":"2019-03-31"].mean()
    for col in daily.columns:
        ax.plot(daily.index, daily[col] / base[col], label=col)
    ax.set_yscale("log")
    ax.legend()
    ax.set_title("npm downloads, 28d MA, indexed to 2019Q1 = 1")

    # (d) Datadog share of instrumentation downloads -- the control-adjusted view
    ax = axes[1, 1]
    share = daily["datadog"] / (daily["datadog"] + daily["control"])
    ax.plot(share.index, share * 100)
    ax.set_title("Datadog share of tracked instrumentation downloads")
    ax.set_ylabel("%")

    fig.tight_layout()
    out = FIG / "phase1_overview.png"
    fig.savefig(out, dpi=140)
    print(f"Wrote {out.relative_to(sc.REPO)}")

    # Smell test only: contemporaneous full-quarter correlation.
    dd = npm[npm["cohort"] == "datadog"].copy()
    dd["quarter"] = dd["date"].dt.to_period("Q").astype(str)
    qs = dd.groupby("quarter", as_index=False)["downloads"].sum()
    qs["npm_yoy"] = qs["downloads"].pct_change(4)
    merged = q.merge(qs, on="quarter", how="inner").dropna(subset=["rev_yoy", "npm_yoy"])
    print(
        "\nSMELL TEST ONLY -- contemporaneous corr(rev_yoy, npm_yoy) = "
        f"{merged['rev_yoy'].corr(merged['npm_yoy']):.3f} (n={len(merged)})"
    )
    print("Uses the full quarter of downloads, so it is not a usable signal.")
    print("Lead-lag, partial-quarter features and walk-forward validation come next.")

    # Absolute vs control-adjusted growth. The quarter in progress is excluded:
    # a partial quarter compared against a full prior-year quarter is not a YoY.
    full = npm[npm["date"] < pd.Timestamp.today().to_period("Q").start_time].copy()
    full["quarter"] = full["date"].dt.to_period("Q").astype(str)
    coh = full.pivot_table(
        index="quarter", columns="cohort", values="downloads", aggfunc="sum"
    )
    coh["dd_share"] = coh["datadog"] / (coh["datadog"] + coh["control"])
    coh["dd_yoy_%"] = (coh["datadog"] / coh["datadog"].shift(4) - 1) * 100
    coh["control_yoy_%"] = (coh["control"] / coh["control"].shift(4) - 1) * 100
    coh["share_yoy_pp"] = (coh["dd_share"] - coh["dd_share"].shift(4)) * 100
    print("\nnpm cohort growth, completed quarters only:")
    print(
        coh[["dd_yoy_%", "control_yoy_%", "dd_share", "share_yoy_pp"]]
        .tail(9)
        .round({"dd_yoy_%": 1, "control_yoy_%": 1, "dd_share": 4, "share_yoy_pp": 2})
        .to_string()
    )
    print(
        "\nRead this before treating absolute downloads as a Datadog signal: the "
        "2026 acceleration appears in the control cohort too."
    )


if __name__ == "__main__":
    main()
