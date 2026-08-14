"""Data-quality cleaning for npm download series.

Two defects found in the raw API responses, both of which would corrupt
downstream features if left in:

1. **Registry-wide missing days.** On some dates the API returns 0 (or a small
   fraction of normal volume) for *every* package simultaneously. These are API
   data gaps, not days on which the world stopped installing software. There
   are 12 such days in 3,512. Four of them fall in 2026Q3 -- the quarter being
   nowcast -- including 2026-08-13, the most recent day available. Left
   uncorrected they would drag the live quarter-to-date pace down and produce a
   spuriously bearish nowcast.

2. **`express` returns zeros before 2021-10-01** (1,734 consecutive zero days)
   while the package was plainly in heavy use throughout. This is a
   package-specific API defect, so `express` is dropped entirely rather than
   patched.

Imputation for defect 1 uses the same package's median volume on the same
weekday within a +/-21 day neighbourhood. Download counts have a strong
day-of-week profile (weekday CI builds dominate), so a plain linear
interpolation across a Monday gap would systematically under-fill it.

Every correction is recorded in data/processed/npm_data_quality.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import sec_common as sc

DROP_PACKAGES = ["express"]  # API returns zeros pre-2021-10; unusable
BAD_DAY_THRESHOLD = 0.20  # day is suspect if registry total < 20% of local median
NEIGHBOURHOOD_DAYS = 21


def find_bad_days(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Dates where the whole registry looks missing, not just one package."""
    total = df.groupby("date")["downloads"].sum().sort_index()
    local_median = total.rolling(7, center=True, min_periods=3).median()
    return total.index[total < BAD_DAY_THRESHOLD * local_median]


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df[~df["package"].isin(DROP_PACKAGES)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = df["downloads"].astype(float)  # imputed values are not integers
    bad = find_bad_days(df)

    df["imputed"] = df["date"].isin(bad)
    records = []
    for pkg, grp in df.groupby("package"):
        s = grp.set_index("date")["downloads"].sort_index()
        clean_s = s.copy()
        clean_s[clean_s.index.isin(bad)] = np.nan
        for day in bad:
            if day not in s.index:
                continue
            window = clean_s[
                (clean_s.index >= day - pd.Timedelta(days=NEIGHBOURHOOD_DAYS))
                & (clean_s.index <= day + pd.Timedelta(days=NEIGHBOURHOOD_DAYS))
            ]
            same_weekday = window[window.index.dayofweek == day.dayofweek]
            fill = same_weekday.median()
            if pd.isna(fill):
                fill = window.median()
            clean_s.loc[day] = fill
            records.append(
                {
                    "date": day.date(),
                    "package": pkg,
                    "raw": s.loc[day],
                    "imputed": fill,
                    "method": "same-weekday median, +/-21d",
                }
            )
        df.loc[grp.index, "downloads"] = clean_s.reindex(grp["date"]).values

    report = pd.DataFrame(records)
    return df, report


def load_clean() -> pd.DataFrame:
    """The single entry point analysis code should use for npm data."""
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    cleaned, _ = clean(raw)
    return cleaned


def main() -> None:
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    cleaned, report = clean(raw)

    out = sc.PROCESSED / "npm_daily_clean.csv"
    cleaned.to_csv(out, index=False)
    rep_out = sc.PROCESSED / "npm_data_quality.csv"
    report.to_csv(rep_out, index=False)

    print(f"Dropped packages: {', '.join(DROP_PACKAGES)} (API defect)")
    print(f"Registry-wide bad days corrected: {report['date'].nunique()}")
    print(f"Package-days imputed: {len(report)}")
    print("\nCorrected dates:")
    per_day = report.groupby("date").agg(
        packages=("package", "count"), raw_total=("raw", "sum"), imputed_total=("imputed", "sum")
    )
    print(per_day.round(0).to_string())
    current_q = pd.Timestamp.today().to_period("Q")
    in_q = [d for d in report["date"].unique() if pd.Timestamp(d).to_period("Q") == current_q]
    print(f"\nOf these, {len(in_q)} fall inside the live quarter ({current_q}): "
          f"{', '.join(str(d) for d in sorted(in_q))}")
    print(f"\nWrote {out.relative_to(sc.REPO)}")
    print(f"Wrote {rep_out.relative_to(sc.REPO)}")


if __name__ == "__main__":
    main()
