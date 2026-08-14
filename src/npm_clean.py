"""Data-quality cleaning for npm download series.

Two defects found in the raw API responses, both of which would corrupt
downstream features if left in:

1. **Registry-wide missing days.** On some dates the API returns 0 (or a small
   fraction of normal volume) for *every* package simultaneously. These are API
   data gaps, not days on which the world stopped installing software. There
   are 12 such days in 3,512 (0.34% of observations). Four of them fall in
   2026Q3 -- the quarter being nowcast -- including 2026-08-13, the most recent
   day available.

2. **`express` returns zeros before 2021-10-01** (1,734 consecutive zero days)
   while the package was plainly in heavy use throughout. This is a
   package-specific API defect, so `express` is dropped entirely.

TWO IMPUTATION VARIANTS, AND THEY ARE NOT INTERCHANGEABLE
---------------------------------------------------------
`imputed_causal` -- backward-only. Fills a gap with the same package's median
    volume on the same weekday over the **prior 42 days only**. Nothing after
    the gap is used, so the filled value would have been computable in real
    time on that date. **This is the only variant permitted to feed the as-of
    panel, the walk-forward validation, and the live quarter-to-date estimate.**

`imputed_centered` -- symmetric +/-21 day window. Uses days after the gap, so a
    value filled this way could not have been known on the date it occupies.
    Strictly better as a descriptive estimate, and strictly illegal in anything
    with an as-of date. **Descriptive charts and the data-quality appendix
    only.** `load_centered()` marks its output with an attribute that the
    feature-path unit test asserts never appears.

Weekday matching (rather than plain interpolation) is used in both because
download counts have a strong day-of-week profile -- weekday CI builds dominate
-- so linear interpolation across a Monday gap systematically under-fills it.

Every correction is recorded in data/processed/npm_data_quality.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import sec_common as sc

DROP_PACKAGES = ["express"]  # API returns zeros pre-2021-10; unusable

# Outage detection rule. Specified and executed before its effect on any
# correlation was computed -- see LOG.md D16 for the ordering evidence. The
# threshold has not been altered since.
BAD_DAY_THRESHOLD = 0.20  # day is suspect if registry total < 20% of local median

CENTERED_WINDOW_DAYS = 21  # symmetric, descriptive only
CAUSAL_LOOKBACK_DAYS = 42  # backward only, six same-weekday observations


def find_bad_days(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Dates where the whole registry looks missing, not just one package.

    Detection uses a centred median deliberately: this is a data-quality
    judgement about which observations are valid, made once over the full
    history, not a feature. The *fill values* are what must respect causality.
    """
    total = df.groupby("date")["downloads"].sum().sort_index()
    local_median = total.rolling(7, center=True, min_periods=3).median()
    return total.index[total < BAD_DAY_THRESHOLD * local_median]


def _fill_value(series: pd.Series, day: pd.Timestamp, mode: str) -> float:
    """Replacement value for one package on one bad day."""
    if mode == "causal":
        window = series[
            (series.index >= day - pd.Timedelta(days=CAUSAL_LOOKBACK_DAYS))
            & (series.index < day)
        ]
    else:
        window = series[
            (series.index >= day - pd.Timedelta(days=CENTERED_WINDOW_DAYS))
            & (series.index <= day + pd.Timedelta(days=CENTERED_WINDOW_DAYS))
        ]
    same_weekday = window[window.index.dayofweek == day.dayofweek]
    fill = same_weekday.median()
    if pd.isna(fill):
        fill = window.median()
    return 0.0 if pd.isna(fill) else float(fill)


def clean(df: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if mode not in ("causal", "centered"):
        raise ValueError(f"mode must be 'causal' or 'centered', got {mode!r}")
    df = df[~df["package"].isin(DROP_PACKAGES)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = df["downloads"].astype(float)
    bad = find_bad_days(df)

    records = []
    for pkg, grp in df.groupby("package"):
        s = grp.set_index("date")["downloads"].sort_index()
        valid = s.copy()
        valid[valid.index.isin(bad)] = np.nan  # never fill a gap from another gap
        for day in bad:
            if day not in s.index:
                continue
            fill = _fill_value(valid, day, mode)
            s.loc[day] = fill
            records.append(
                {
                    "date": day.date(),
                    "package": pkg,
                    "raw": grp.set_index("date")["downloads"].loc[day],
                    "imputed": fill,
                    "mode": mode,
                }
            )
        df.loc[grp.index, "downloads"] = s.reindex(grp["date"]).values

    df["is_imputed"] = df["date"].isin(bad)
    df["impute_mode"] = mode
    return df, pd.DataFrame(records)


def load_causal() -> pd.DataFrame:
    """Backward-only fills. The ONLY loader permitted on a feature path."""
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    cleaned, _ = clean(raw, mode="causal")
    cleaned.attrs["impute_mode"] = "causal"
    return cleaned


def load_centered() -> pd.DataFrame:
    """Symmetric fills. Descriptive charts and the appendix only.

    The returned frame is tagged so the feature-path unit test can assert that
    nothing built for the as-of panel ever came through here.
    """
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    cleaned, _ = clean(raw, mode="centered")
    cleaned.attrs["impute_mode"] = "centered"
    cleaned.attrs["forbidden_on_feature_path"] = True
    return cleaned


def load_raw_with_zeros() -> pd.DataFrame:
    """Untouched series, outage days left as reported. Sensitivity analysis."""
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    raw = raw[~raw["package"].isin(DROP_PACKAGES)].copy()
    raw["downloads"] = raw["downloads"].astype(float)
    raw["is_imputed"] = False
    raw.attrs["impute_mode"] = "raw"
    return raw


def bad_days() -> pd.DatetimeIndex:
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    raw = raw[~raw["package"].isin(DROP_PACKAGES)]
    return find_bad_days(raw)


def main() -> None:
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    causal, rep_c = clean(raw, mode="causal")
    centered, rep_s = clean(raw, mode="centered")

    causal.to_csv(sc.PROCESSED / "npm_daily_causal.csv", index=False)
    centered.to_csv(sc.PROCESSED / "npm_daily_centered.csv", index=False)
    report = pd.concat([rep_c, rep_s], ignore_index=True)
    report.to_csv(sc.PROCESSED / "npm_data_quality.csv", index=False)

    n_days = raw["date"].nunique()
    n_bad = rep_c["date"].nunique()
    print(f"Dropped packages: {', '.join(DROP_PACKAGES)} (API defect)")
    print(f"Registry-wide bad days: {n_bad} of {n_days} "
          f"({n_bad / n_days * 100:.2f}% of observations)")
    print(f"Package-days imputed: {len(rep_c)} per variant\n")

    comp = (
        rep_c.merge(rep_s, on=["date", "package"], suffixes=("_causal", "_centered"))
        .groupby("date")[["raw_causal", "imputed_causal", "imputed_centered"]]
        .sum()
        .rename(columns={"raw_causal": "raw"})
    )
    comp["causal_vs_centered_%"] = (
        comp["imputed_causal"] / comp["imputed_centered"] - 1
    ) * 100
    print("Totals by date, both variants:")
    print(comp.round(0).to_string())

    current_q = pd.Timestamp.today().to_period("Q")
    in_q = sorted(d for d in rep_c["date"].unique() if pd.Timestamp(d).to_period("Q") == current_q)
    elapsed = (pd.Timestamp.today().normalize() - current_q.start_time).days
    print(f"\nLive quarter {current_q}: {len(in_q)} of ~{elapsed} elapsed days imputed "
          f"({len(in_q) / elapsed * 100:.1f}%)")
    print(f"  {', '.join(str(d) for d in in_q)}")
    print("\nWrote npm_daily_causal.csv, npm_daily_centered.csv, npm_data_quality.csv")
    print("Feature paths must use load_causal(). load_centered() is charts only.")


if __name__ == "__main__":
    main()
