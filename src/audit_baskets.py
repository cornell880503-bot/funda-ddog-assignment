"""D22 -- basket composition audit.

The outage problem (D16) was an artificial *drop* in basket volume on specific
days. Basket composition drift is the mirror image: when a package is first
published, adding it to a "sum of packages that exist today" basket creates an
artificial *jump* in the basket total -- and unlike an outage, the distortion is
permanent, not a spike. `@datadog/browser-rum` and `@datadog/browser-logs` did
not exist in 2019; `@datadog/datadog-ci` did not exist until 2020.

Both baskets are audited by the same rule, because treating the Datadog basket
differently from its controls would itself be a bias.

Two variants:
  basket_all     every package currently in the basket definition
  basket_common  only packages with continuous history across the full sample

Outputs:
  processed/basket_composition.csv
  report/figures/basket_divergence.png
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import npm_clean
import sec_common as sc

# What counts as "present". The concern is composition drift: a package that
# did NOT EXIST entering the basket creates a permanent artificial jump. A
# package that existed throughout and merely grew does not -- that is signal,
# not drift. So presence is defined by existence, with a low floor only to
# exclude the publication trickle of the first few weeks.
VOLUME_FLOOR = 1_000  # downloads/day, 28d mean

# The modelling sample. Targets with a reliable disclosure date and a computable
# YoY run 2020Q1..2026Q2 (2019Q3 is isolated and has no usable feature history).
# A YoY feature for 2020Q1 needs the 2019Q1 window, so a package must be present
# from 2019-01-01 to contribute without creating a jump inside the sample.
FIRST_TARGET_QUARTER = pd.Period("2020Q1", freq="Q")
SAMPLE_START = (FIRST_TARGET_QUARTER - 4).start_time

BASKETS = {
    "dd": ["dd-trace", "@datadog/browser-rum", "@datadog/browser-logs",
           "datadog-metrics", "@datadog/datadog-ci"],
    "ctrl": ["newrelic", "elastic-apm-node"],
    "placebo": ["lodash", "chalk", "axios", "react"],
}


def first_nontrivial(s: pd.Series) -> pd.Timestamp | None:
    ma = s.sort_index().rolling(28, min_periods=28).mean()
    above = ma[ma >= VOLUME_FLOOR]
    return above.index[0] if len(above) else None


def audit(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for basket, pkgs in BASKETS.items():
        for pkg in pkgs:
            s = daily[daily["package"] == pkg].set_index("date")["downloads"]
            first_nz = s[s > 0].index.min() if (s > 0).any() else None
            first_nt = first_nontrivial(s)
            rows.append(
                {
                    "basket": basket,
                    "package": pkg,
                    "first_nonzero": first_nz.date() if first_nz is not None else None,
                    "first_nontrivial": first_nt.date() if first_nt is not None else None,
                    "continuous_from_sample_start": bool(
                        first_nt is not None and first_nt <= SAMPLE_START
                    ),
                    "last30d_mean": s.tail(30).mean(),
                }
            )
    return pd.DataFrame(rows)


def basket_series(daily: pd.DataFrame, pkgs: list[str]) -> pd.Series:
    return (
        daily[daily["package"].isin(pkgs)]
        .groupby("date")["downloads"]
        .sum()
        .sort_index()
    )


def quarterly_yoy_log(s: pd.Series) -> pd.Series:
    q = s.groupby(s.index.to_period("Q")).sum()
    return np.log(q) - np.log(q.shift(4))


def main() -> None:
    daily = npm_clean.load_causal()
    comp = audit(daily)
    comp.to_csv(sc.PROCESSED / "basket_composition.csv", index=False)

    pd.set_option("display.width", 200)
    print(f"First target quarter {FIRST_TARGET_QUARTER}; feature history must start "
          f"by {SAMPLE_START.date()} (one year earlier, for the YoY window)")
    print("Package availability (floor = {:,}/day, 28d mean)".format(VOLUME_FLOOR))
    print(comp.round(0).to_string(index=False))

    print("\nSample start:", SAMPLE_START.date())
    common = {}
    for basket, pkgs in BASKETS.items():
        keep = comp[(comp["basket"] == basket) & comp["continuous_from_sample_start"]]
        common[basket] = list(keep["package"])
        dropped = sorted(set(pkgs) - set(common[basket]))
        print(f"  {basket:<8} common = {common[basket]}")
        if dropped:
            print(f"           dropped  = {dropped}")

    # ---- divergence between the two variants ----
    print("\nQuarterly YoY log growth, basket_all vs basket_common")
    frames = {}
    for basket, pkgs in BASKETS.items():
        all_s = quarterly_yoy_log(basket_series(daily, pkgs))
        com_s = quarterly_yoy_log(basket_series(daily, common[basket]))
        df = pd.DataFrame({"all": all_s, "common": com_s})
        df["diff"] = df["all"] - df["common"]
        frames[basket] = df

    summary = []
    for basket, df in frames.items():
        d = df.dropna()
        in_sample = d[d.index >= pd.Period("2020Q1", freq="Q")]
        summary.append(
            {
                "basket": basket,
                "mean_abs_diff": in_sample["diff"].abs().mean(),
                "max_abs_diff": in_sample["diff"].abs().max(),
                "max_diff_quarter": str(in_sample["diff"].abs().idxmax())
                if len(in_sample) else "",
                "corr": in_sample["all"].corr(in_sample["common"]),
                "diff_last_4q": in_sample["diff"].tail(4).abs().mean(),
            }
        )
    summ = pd.DataFrame(summary)
    print(summ.round(4).to_string(index=False))

    print("\nDatadog basket, quarter by quarter (log points):")
    print(frames["dd"].dropna().round(4).tail(20).to_string())

    # Relative features under both variants.
    print("\nRelative features: does composition drift survive the difference?")
    rel_rows = []
    for label, pkgmap in (("all", BASKETS), ("common", common)):
        dd = quarterly_yoy_log(basket_series(daily, pkgmap["dd"]))
        ct = quarterly_yoy_log(basket_series(daily, pkgmap["ctrl"]))
        pl = quarterly_yoy_log(basket_series(daily, pkgmap["placebo"]))
        rel_rows.append(
            pd.DataFrame(
                {
                    f"dd_abs_{label}": dd,
                    f"dd_rel_{label}": dd - ct,
                    f"dd_rel_vs_plc_{label}": dd - pl,
                }
            )
        )
    rel = pd.concat(rel_rows, axis=1).dropna()
    rel = rel[rel.index >= pd.Period("2020Q1", freq="Q")]
    for feat in ("dd_abs", "dd_rel", "dd_rel_vs_plc"):
        diff = (rel[f"{feat}_all"] - rel[f"{feat}_common"]).abs()
        print(f"  {feat:<16} mean |all - common| = {diff.mean():.4f}   "
              f"max = {diff.max():.4f}   corr = "
              f"{rel[f'{feat}_all'].corr(rel[f'{feat}_common']):.4f}")

    # ---- figure ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    d = frames["dd"].dropna()
    d = d[d.index >= pd.Period("2020Q1", freq="Q")]
    x = [p.to_timestamp() for p in d.index]
    axes[0].plot(x, d["all"], marker="o", ms=3, label="basket_all")
    axes[0].plot(x, d["common"], marker="s", ms=3, label="basket_common")
    axes[0].set_title("Datadog basket YoY log growth")
    axes[0].legend()
    axes[1].bar(x, d["diff"], width=60)
    axes[1].axhline(0, lw=0.5, color="grey")
    axes[1].set_title("all - common (log points)")
    fig.tight_layout()
    out = sc.REPO / "report" / "figures" / "basket_divergence.png"
    fig.savefig(out, dpi=140)
    print(f"\nWrote {out.relative_to(sc.REPO)}")
    print(f"Wrote {(sc.PROCESSED / 'basket_composition.csv').relative_to(sc.REPO)}")


if __name__ == "__main__":
    main()
