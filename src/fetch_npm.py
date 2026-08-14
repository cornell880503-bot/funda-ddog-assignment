"""Pull daily npm download counts for Datadog instrumentation libraries and a
control cohort.

Why these packages: Datadog bills on hosts, custom metrics, ingested spans and
logs. Customers emit that telemetry by installing an agent or tracing library,
so download volume is a proxy for the billable unit rather than for sentiment.
The control cohort (OpenTelemetry, New Relic, Elastic APM) is mandatory: if
Datadog packages and controls move together, the series is measuring ecosystem
growth, not Datadog adoption.

API: https://api.npmjs.org/downloads/range/{start}:{end}/{package}
Free, no auth, daily granularity, history back to 2015, max 18 months per call
so we page through. Raw responses are cached one file per package per window.

Outputs:
  raw/npm_<pkg>_<start>_<end>_<ts>.json
  processed/npm_daily.csv   date, package, cohort, downloads
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta

import pandas as pd
import requests

import sec_common as sc

DATADOG_PACKAGES = [
    "dd-trace",  # Node.js APM tracer -- the core billable instrumentation
    "@datadog/browser-rum",  # Real User Monitoring
    "@datadog/browser-logs",  # browser log collection
    "datadog-metrics",  # custom metrics submission
    "@datadog/datadog-ci",  # CI Visibility / test optimization
]
CONTROL_PACKAGES = [
    "@opentelemetry/api",  # vendor-neutral instrumentation standard
    "newrelic",  # direct competitor APM agent
    "elastic-apm-node",  # direct competitor APM agent
    "@sentry/node",  # adjacent observability vendor
]
# Negative control. These have no economic link to Datadog's revenue whatsoever
# -- they are general-purpose JavaScript utilities. Identical features are built
# from them and pushed through the identical as-of construction and
# walk-forward validation. If a placebo feature predicts Datadog's results as
# well as the Datadog feature does, the Datadog feature is measuring shared
# ecosystem trend and not Datadog adoption. This is evidence design, not a
# robustness afterthought.
PLACEBO_PACKAGES = [
    "lodash",
    "express",
    "chalk",
    "axios",
    "react",
]

START = date(2017, 1, 1)
BASE = "https://api.npmjs.org/downloads/range"
SLEEP = 0.35  # be polite to the public registry API


def _windows(start: date, end: date, months: int = 17):
    """Yield <=17-month windows; the API rejects ranges longer than 18 months."""
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=int(months * 30.4)), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_package(pkg: str, start: date, end: date, force: bool = False) -> pd.DataFrame:
    rows = []
    safe = pkg.replace("/", "__").replace("@", "")
    for w_start, w_end in _windows(start, end):
        name = f"npm_{safe}_{w_start}_{w_end}"
        cached = sorted(sc.RAW.glob(f"{name}_*.json"))
        if cached and not force:
            with open(cached[-1]) as fh:
                payload = json.load(fh)
        else:
            url = f"{BASE}/{w_start}:{w_end}/{pkg}"
            resp = requests.get(url, timeout=60)
            time.sleep(SLEEP)
            if resp.status_code == 404:
                print(f"  {pkg}: 404 for {w_start}..{w_end} (package not yet published)")
                continue
            resp.raise_for_status()
            payload = resp.json()
            out = sc.RAW / f"{name}_{sc.utc_stamp()}.json"
            with open(out, "w") as fh:
                json.dump(payload, fh)
        for d in payload.get("downloads", []):
            rows.append({"date": d["day"], "package": pkg, "downloads": d["downloads"]})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.drop_duplicates(subset=["date", "package"]).sort_values("date")
    return df


def qtd_pace(panel: pd.DataFrame) -> pd.DataFrame:
    """Cumulative downloads by day-of-quarter, per cohort.

    This is the matrix behind the dashboard's pace chart (where is the current
    quarter on day N versus where prior quarters sat on their day N) and behind
    the partial-quarter features (at day 45 only the first 45 days may be
    used). day_of_quarter is derived from the calendar date, not from a running
    row count, so a missing day in the API response cannot silently shift the
    whole quarter's alignment.
    """
    df = panel.copy()
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby(["cohort", "date"], as_index=False)["downloads"].sum()
    q = daily["date"].dt.to_period("Q")
    daily["quarter"] = q.astype(str)
    daily["day_of_quarter"] = (daily["date"] - q.dt.start_time).dt.days + 1
    daily = daily.sort_values(["cohort", "date"])
    daily["cum_downloads"] = daily.groupby(["cohort", "quarter"])["downloads"].cumsum()
    return daily[
        ["cohort", "quarter", "date", "day_of_quarter", "downloads", "cum_downloads"]
    ]


def main(force: bool = False, end: str | None = None) -> None:
    end_date = date.fromisoformat(end) if end else date.today() - timedelta(days=1)
    frames = []
    for cohort, pkgs in (
        ("datadog", DATADOG_PACKAGES),
        ("control", CONTROL_PACKAGES),
        ("placebo", PLACEBO_PACKAGES),
    ):
        for pkg in pkgs:
            print(f"npm: {pkg}")
            df = fetch_package(pkg, START, end_date, force=force)
            if df.empty:
                print(f"  no data for {pkg}")
                continue
            df["cohort"] = cohort
            nonzero = df[df["downloads"] > 0]
            print(
                f"  {len(df)} days, first non-zero {nonzero['date'].min()}, "
                f"last {df['date'].max()}, last-30d mean "
                f"{df.tail(30)['downloads'].mean():,.0f}/day"
            )
            frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = sc.PROCESSED / "npm_daily.csv"
    panel.to_csv(out, index=False)
    print(f"\nWrote {out.relative_to(sc.REPO)}  ({len(panel):,} rows)")

    pace = qtd_pace(panel)
    pace_out = sc.PROCESSED / "npm_qtd_pace.csv"
    pace.to_csv(pace_out, index=False)
    print(f"Wrote {pace_out.relative_to(sc.REPO)}  ({len(pace):,} rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD, defaults to yesterday")
    main(**vars(ap.parse_args()))
