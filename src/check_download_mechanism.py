"""Does download volume still proxy the billable unit?

Part 1's economic argument is that installs of instrumentation libraries proxy
Datadog's billable units (hosts, custom metrics, ingested spans and logs). The
constant-composition Datadog basket grew ~112% YoY in the live quarter against
~36% revenue growth -- a factor of three. A gap is expected (downloads need not
scale one-for-one with billing), but a persistent 3x gap is evidence against
the coupling and has to be addressed in the main body, not filed under
limitations.

The leading candidate explanation: a rising share of downloads are CI/CD
re-pulls rather than deployments. Two testable implications, both from data
already held:

  1. **Weekday concentration should rise.** CI builds run on working days;
     human-driven and production installs are less weekday-skewed. A rising
     weekday/weekend ratio implies a rising CI share.
  2. **Release-window concentration should change.** If downloads increasingly
     track automated dependency updates, the share of volume in the days right
     after a new version publishes should drift.

Both are indirect. Neither can prove the CI hypothesis, and the report says so.

Outputs:
  processed/download_mechanism.csv
  report/figures/download_mechanism.png
"""

from __future__ import annotations

import json
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from scipy import stats

import npm_clean
import sec_common as sc

DD_BASKET = ["dd-trace", "datadog-metrics"]  # constant composition, LOG D22
RELEASE_WINDOW_DAYS = 7


def weekday_ratio(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily[daily["package"].isin(DD_BASKET)].copy()
    d = d.groupby("date", as_index=False)["downloads"].sum()
    d["quarter"] = d["date"].dt.to_period("Q")
    d["is_weekend"] = d["date"].dt.dayofweek >= 5
    g = d.groupby(["quarter", "is_weekend"])["downloads"].mean().unstack()
    g.columns = ["weekday_mean", "weekend_mean"]
    g["weekday_weekend_ratio"] = g["weekday_mean"] / g["weekend_mean"]
    return g


def release_dates(package: str = "dd-trace") -> list[pd.Timestamp]:
    cache = sc.RAW / f"npm_releases_{package.replace('/', '__')}.json"
    if cache.exists():
        payload = json.loads(cache.read_text())
    else:
        r = requests.get(f"https://registry.npmjs.org/{package}", headers=sc.HEADERS,
                         timeout=60)
        time.sleep(0.3)
        r.raise_for_status()
        payload = r.json()["time"]
        cache.write_text(json.dumps(payload))
    out = []
    for ver, ts in payload.items():
        if ver in ("created", "modified"):
            continue
        out.append(pd.Timestamp(ts).tz_localize(None).normalize())
    return sorted(out)


def release_concentration(daily: pd.DataFrame, releases: list[pd.Timestamp]) -> pd.DataFrame:
    d = daily[daily["package"] == "dd-trace"].copy()
    d = d.groupby("date", as_index=False)["downloads"].sum().set_index("date")
    rel = pd.Series(0, index=d.index, dtype=int)
    for r in releases:
        window = pd.date_range(r, r + pd.Timedelta(days=RELEASE_WINDOW_DAYS - 1))
        rel.loc[rel.index.isin(window)] = 1
    d["in_release_window"] = rel
    d["quarter"] = d.index.to_period("Q")
    g = d.groupby("quarter").apply(
        lambda x: pd.Series(
            {
                "share_days_in_window": x["in_release_window"].mean(),
                "share_volume_in_window": x.loc[x["in_release_window"] == 1, "downloads"].sum()
                / x["downloads"].sum(),
            }
        ),
        include_groups=False,
    )
    g["concentration_index"] = g["share_volume_in_window"] / g["share_days_in_window"]
    return g


def main() -> None:
    # Descriptive analysis, so the centred variant is the right loader here.
    daily = npm_clean.load_centered()
    pd.set_option("display.width", 200)

    wk = weekday_ratio(daily)
    rc = release_concentration(daily, release_dates())
    out = wk.join(rc, how="inner")
    out = out[out.index >= pd.Period("2019Q1", freq="Q")]
    # Drop the quarter in progress: a partial quarter's shares are not
    # comparable to complete ones.
    out = out[out.index < pd.Timestamp.today().to_period("Q")]

    # The direct decoupling measure. If downloads still proxy billable units,
    # downloads per dollar of revenue should be roughly stable. Its trend is
    # exactly what "download inflation relative to billing" means, and unlike
    # the two indirect tests it does not depend on identifying a mechanism.
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    q = q[q["known_from_reliable"]][["quarter", "revenue_musd"]]
    dl = daily[daily["package"].isin(DD_BASKET)].copy()
    dl["quarter"] = dl["date"].dt.to_period("Q")
    dlq = dl.groupby("quarter")["downloads"].sum().rename("downloads")
    q["quarter"] = pd.PeriodIndex(q["quarter"], freq="Q")
    dec = q.set_index("quarter").join(dlq, how="inner").dropna()
    dec["downloads_per_musd"] = dec["downloads"] / dec["revenue_musd"]
    out = out.join(dec["downloads_per_musd"], how="left")
    out.to_csv(sc.PROCESSED / "download_mechanism.csv")

    print("Weekday/weekend ratio and release-window concentration, by quarter")
    print(out[["weekday_weekend_ratio", "share_volume_in_window",
               "concentration_index"]].round(3).to_string())

    # Trend tests. A rising weekday/weekend ratio is consistent with a rising
    # CI share, which would dilute downloads as a proxy for deployments.
    x = np.arange(len(out))
    print("\nTrend tests (OLS slope per quarter, and Spearman):")
    for col in ("weekday_weekend_ratio", "concentration_index", "downloads_per_musd"):
        y = out[col].values
        ok = np.isfinite(y)
        slope, intercept, r, p, se = stats.linregress(x[ok], y[ok])
        rho, prho = stats.spearmanr(x[ok], y[ok])
        print(f"  {col:<26} slope={slope:+.4f}/qtr  p={p:.4f}  "
              f"spearman rho={rho:+.3f} p={prho:.4f}")

    first, last = out.iloc[:4], out.iloc[-4:]
    print(f"\nWeekday/weekend ratio: {first['weekday_weekend_ratio'].mean():.2f} "
          f"(first 4 quarters) -> {last['weekday_weekend_ratio'].mean():.2f} (last 4)")
    print(f"Release-window volume share: {first['share_volume_in_window'].mean():.3f} "
          f"-> {last['share_volume_in_window'].mean():.3f}")
    d0, d1 = first["downloads_per_musd"].mean(), last["downloads_per_musd"].mean()
    print(f"Downloads per $m of revenue: {d0:,.0f} -> {d1:,.0f}  "
          f"({d1 / d0 - 1:+.0%} over the sample)")
    print("\nThe release-window test is underpowered and is reported as such: "
          "\ndd-trace publishes so frequently that a 7-day post-release window "
          "\ncovers most of the calendar, so the concentration index sits at ~1.0 "
          "\nby construction and cannot discriminate.")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    t = [p.to_timestamp() for p in out.index]
    axes[0].plot(t, out["weekday_weekend_ratio"], marker="o", ms=3)
    axes[0].set_title("Weekday / weekend download ratio\n(rising = more CI-like)", fontsize=10)
    axes[1].plot(t, out["concentration_index"], marker="o", ms=3)
    axes[1].axhline(1, lw=0.5, color="grey")
    axes[1].set_title("Release-window concentration index\n(volume share / day share)",
                      fontsize=10)
    fig.tight_layout()
    fig.savefig(sc.REPO / "report" / "figures" / "download_mechanism.png", dpi=140)
    print("\nWrote report/figures/download_mechanism.png")


if __name__ == "__main__":
    main()
