"""Signal 2 -- hyperscaler cloud segment growth, extracted from press releases.

Why this cannot come from XBRL: the `companyfacts` endpoint returns
consolidated facts only and drops the dimensional (segment) axis, so AWS /
Intelligent Cloud / Google Cloud revenue is simply not in it (LOG D15). The
values come from the same place an analyst would read them -- the Item 2.02
8-K press release -- extracted verbatim, cached, and audited.

Each signal gets a MATCHED NON-CLOUD CONTROL from the *same filing*: Amazon's
total net sales and Alphabet's Search & other. These share the issuer, the
quarter, the macro environment and the extraction method, but they are not the
cloud workload pool that Datadog bills against. If the control tracks Datadog's
results as well as the cloud segment does, the cloud segment is measuring the
macro cycle rather than cloud consumption.

Timing is already verified (LOG D15): all three peers reported before Datadog
in all 28 quarters, median lead 7 days for Amazon.

Outputs:
  raw/8k_peer_<ticker>_<accn>.txt
  processed/hyperscaler_segment_growth.csv
"""

from __future__ import annotations

import re
import time

import pandas as pd
import requests

import fetch_guidance as fg
import sec_common as sc

# Growth-rate patterns. Multiple alternatives per series because the wording
# drifts across eight years of press releases.
#
# S is "any character except a sentence-ending period": a bare [^.] breaks
# inside dollar amounts ("$39.3 billion"), which is exactly the trap that hid
# two quarters of Datadog guidance in D6. Same bug, same fix.
S = r"(?:[^.]|\.\d)"
PATTERNS = {
    "aws_yoy": [
        rf"AWS (?:net sales|segment sales|revenue){S}{{0,80}}?increased (\d+(?:\.\d+)?)%",
        rf"AWS{S}{{0,60}}?(?:sales|revenue){S}{{0,60}}?(?:grew|increased|up) (\d+(?:\.\d+)?)%",
        rf"AWS segment{S}{{0,80}}?(?:grew|increased|up) (\d+(?:\.\d+)?)%",
    ],
    "gcp_yoy": [
        rf"Google Cloud{S}{{0,200}}?revenues?{S}{{0,40}}?increased (\d+(?:\.\d+)?)%",
        rf"Google Cloud{S}{{0,200}}?(?:grew|up) (\d+(?:\.\d+)?)%",
    ],
    "azure_ic_yoy": [
        rf"Intelligent Cloud{S}{{0,120}}?increased (\d+(?:\.\d+)?)%",
        rf"Intelligent Cloud{S}{{0,60}}?(?:revenue|segment){S}{{0,80}}?(?:grew|up) (\d+(?:\.\d+)?)%",
    ],
    # ---- matched non-cloud controls, same filings ----
    "amzn_total_yoy": [
        r"Net sales increased (\d+(?:\.\d+)?)%",
        rf"net sales{S}{{0,40}}?increased (\d+(?:\.\d+)?)%",
    ],
    "msft_pbp_yoy": [
        rf"Productivity and Business Processes{S}{{0,120}}?increased (\d+(?:\.\d+)?)%",
    ],
    "goog_search_yoy": [
        rf"Google Search & other{S}{{0,80}}?(?:increased|grew|up) (\d+(?:\.\d+)?)%",
        r"(\d+(?:\.\d+)?)% growth in Google Search & other",
    ],
}
SERIES_BY_TICKER = {
    "AMZN": ["aws_yoy", "amzn_total_yoy"],
    "GOOGL": ["gcp_yoy", "goog_search_yoy"],
    "MSFT": ["azure_ic_yoy", "msft_pbp_yoy"],
}


def exhibit_text(ticker: str, accn: str, force: bool = False) -> str:
    cache = sc.RAW / f"8k_peer_{ticker}_{accn}.txt"
    if cache.exists() and not force:
        return cache.read_text()
    cik = int(sc.CIK[ticker])
    nodash = accn.replace("-", "")
    idx = requests.get(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/index.json",
        headers=sc.HEADERS,
        timeout=60,
    )
    time.sleep(sc.SLEEP_SECONDS)
    idx.raise_for_status()
    items = [
        i
        for i in idx.json()["directory"]["item"]
        if i["name"].lower().endswith((".htm", ".html"))
        and not i["name"].lower().startswith("r")
        and "index" not in i["name"].lower()
    ]
    items.sort(key=lambda i: int(i.get("size", 0)), reverse=True)
    if not items:
        return ""
    resp = requests.get(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{items[0]['name']}",
        headers=sc.HEADERS,
        timeout=60,
    )
    time.sleep(sc.SLEEP_SECONDS)
    resp.raise_for_status()
    text = fg.strip_html(resp.text)
    cache.write_text(text)
    return text


def extract(text: str, series: str) -> tuple[float | None, str | None]:
    for pat in PATTERNS[series]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            snippet = text[max(0, m.start() - 60) : m.end() + 60]
            return float(m.group(1)) / 100, snippet
    return None, None


def main(force: bool = False) -> None:
    dates = pd.read_csv(
        sc.PROCESSED / "hyperscaler_earnings_dates.csv", parse_dates=["peer_earnings_date"]
    )
    rows = []
    for _, r in dates.iterrows():
        series_list = SERIES_BY_TICKER[r["ticker"]]
        try:
            text = exhibit_text(r["ticker"], r["peer_accn"], force=force)
        except Exception as exc:
            print(f"  {r['ticker']} {r['quarter']}: fetch failed ({exc})")
            continue
        for series in series_list:
            val, snip = extract(text, series)
            rows.append(
                {
                    "quarter": r["quarter"],
                    "ticker": r["ticker"],
                    "series": series,
                    "yoy": val,
                    "available_from": r["peer_earnings_date"].date(),
                    "ddog_earnings_date": r["ddog_earnings_date"],
                    "lead_days": r["lead_days"],
                    "accession": r["peer_accn"],
                    "snippet": (snip or "")[:200],
                }
            )
    df = pd.DataFrame(rows)
    out = sc.PROCESSED / "hyperscaler_segment_growth.csv"
    df.to_csv(out, index=False)

    pd.set_option("display.width", 200)
    print("Extraction rate by series:")
    rate = df.groupby("series")["yoy"].agg(["count", "size"])
    rate["rate_%"] = rate["count"] / rate["size"] * 100
    print(rate.to_string())

    piv = df.pivot_table(index="quarter", columns="series", values="yoy")
    print("\nSegment YoY growth, last 12 quarters:")
    print((piv.tail(12) * 100).round(1).to_string())
    print(f"\nWrote {out.relative_to(sc.REPO)}")

    # Audit: growth series should evolve smoothly. A jump beyond 25pp between
    # consecutive quarters is more likely a misparse than a real move.
    print("\nAudit -- quarter-on-quarter jumps greater than 25pp:")
    flagged = []
    for col in piv.columns:
        d = piv[col].dropna().diff().abs()
        for q, v in d[d > 0.25].items():
            flagged.append({"series": col, "quarter": q, "jump_pp": v * 100})
    print(pd.DataFrame(flagged).to_string(index=False) if flagged else "  none")


if __name__ == "__main__":
    main()
