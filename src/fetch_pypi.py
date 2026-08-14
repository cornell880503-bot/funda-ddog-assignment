"""Pull PyPI download counts for Datadog's Python libraries and controls.

Two paths, deliberately kept separate:

1. pypistats.org public API -- free, no auth, but only ~180 days of daily
   history. Enough for a recent-period cross-check against the npm signal,
   NOT enough to fit or validate a model over 8-12+ quarters.
2. BigQuery public dataset `bigquery-public-data.pypi.file_downloads` -- full
   history, but requires a Google Cloud project with billing enabled (the
   dataset is free to store, the query scan is billed to the caller).

Path 2 is off by default. Run with --bigquery only after confirming a project
is available; the report must state which path produced the numbers.

Outputs:
  raw/pypistats_<pkg>_<ts>.json
  processed/pypi_daily_180d.csv    date, package, cohort, downloads
"""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd
import requests

import sec_common as sc

DATADOG_PACKAGES = ["ddtrace", "datadog", "datadog-api-client"]
CONTROL_PACKAGES = ["opentelemetry-api", "newrelic", "elastic-apm", "sentry-sdk"]

API = "https://pypistats.org/api/packages/{pkg}/overall"
SLEEP = 1.0  # pypistats asks for gentle usage


def fetch_package(pkg: str, force: bool = False) -> pd.DataFrame:
    cached = sorted(sc.RAW.glob(f"pypistats_{pkg}_*.json"))
    if cached and not force:
        with open(cached[-1]) as fh:
            payload = json.load(fh)
    else:
        resp = requests.get(
            API.format(pkg=pkg),
            headers={"User-Agent": sc.USER_AGENT},
            timeout=60,
        )
        time.sleep(SLEEP)
        resp.raise_for_status()
        payload = resp.json()
        out = sc.RAW / f"pypistats_{pkg}_{sc.utc_stamp()}.json"
        with open(out, "w") as fh:
            json.dump(payload, fh)
    rows = [
        {"date": r["date"], "package": pkg, "downloads": r["downloads"]}
        # "without_mirrors" strips known mirror/proxy traffic, one of the
        # documented biases in raw download counts.
        for r in payload["data"]
        if r["category"] == "without_mirrors"
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date")
    return df


def main(force: bool = False, bigquery: bool = False) -> None:
    if bigquery:
        raise SystemExit(
            "BigQuery path not enabled. Confirm a GCP project is available and "
            "implement the query in this function before using it."
        )
    frames = []
    for cohort, pkgs in (("datadog", DATADOG_PACKAGES), ("control", CONTROL_PACKAGES)):
        for pkg in pkgs:
            print(f"pypi: {pkg}")
            df = fetch_package(pkg, force=force)
            if df.empty:
                print("  no data")
                continue
            df["cohort"] = cohort
            print(
                f"  {len(df)} days, {df['date'].min()} .. {df['date'].max()}, "
                f"last-30d mean {df.tail(30)['downloads'].mean():,.0f}/day"
            )
            frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = sc.PROCESSED / "pypi_daily_180d.csv"
    panel.to_csv(out, index=False)
    print(f"\nWrote {out.relative_to(sc.REPO)}  ({len(panel):,} rows)")
    print(
        "NOTE: ~180 days only. Usable as a recent-period cross-check, not as "
        "model history. Long history requires the BigQuery public dataset."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--bigquery", action="store_true")
    main(**vars(ap.parse_args()))
