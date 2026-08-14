"""Hyperscaler earnings timing versus Datadog's.

Signal 2 in the brief rests on a timing claim: Amazon reports roughly two weeks
before Datadog, so AWS growth is a genuine information lead rather than a
coincident read. The brief says to verify this from actual filing dates instead
of assuming it. This script does exactly that, per quarter, for AWS (Amazon),
Azure (Microsoft) and Google Cloud (Alphabet).

Note on Microsoft: its fiscal year ends in June, so its "Q1" is the September
calendar quarter. Everything here is keyed on the calendar quarter being
reported, not on the fiscal label.

Only the earnings dates come from this script. Segment revenue values are not
exposed by the XBRL companyfacts API -- that endpoint returns consolidated
facts only, and segment figures carry a dimensional axis that the API drops.
They therefore have to come from the press releases, handled separately.

Outputs:
  processed/hyperscaler_earnings_dates.csv
"""

from __future__ import annotations

import pandas as pd

import sec_common as sc

PEERS = {"AMZN": "AWS", "MSFT": "Azure / Intelligent Cloud", "GOOGL": "Google Cloud"}


def earnings_dates(ticker: str) -> pd.DataFrame:
    subs = sc.submissions(ticker)
    recent = subs["filings"]["recent"]
    frames = [pd.DataFrame({k: recent[k] for k in ("form", "filingDate", "accessionNumber", "items")})]
    for chunk in subs["filings"].get("files", []):
        payload = sc.get_json(
            f"https://data.sec.gov/submissions/{chunk['name']}",
            f"sec_submissions_chunk_{chunk['name'].replace('.json', '')}",
        )
        frames.append(
            pd.DataFrame({k: payload[k] for k in ("form", "filingDate", "accessionNumber", "items")})
        )
    df = pd.concat(frames, ignore_index=True)
    df = df[(df["form"] == "8-K") & (df["items"].str.contains("2.02", na=False))].copy()
    df["filed"] = pd.to_datetime(df["filingDate"])
    df["ticker"] = ticker
    return df[["ticker", "filed", "accessionNumber"]].sort_values("filed")


def main() -> None:
    ddog = pd.read_csv(
        sc.PROCESSED / "ddog_quarters.csv", parse_dates=["end", "earnings_date"]
    )
    ddog = ddog[ddog["known_from_reliable"]].dropna(subset=["earnings_date"])

    rows = []
    for ticker in PEERS:
        print(f"Fetching {ticker} earnings dates ...")
        peer = earnings_dates(ticker)
        for _, q in ddog.iterrows():
            # The peer release covering the same calendar quarter: the first
            # Item 2.02 8-K filed after that quarter ended.
            cand = peer[peer["filed"] > q["end"]]
            if cand.empty:
                continue
            hit = cand.iloc[0]
            rows.append(
                {
                    "quarter": q["quarter"],
                    "quarter_end": q["end"].date(),
                    "ticker": ticker,
                    "segment": PEERS[ticker],
                    "peer_earnings_date": hit["filed"].date(),
                    "ddog_earnings_date": q["earnings_date"].date(),
                    "lead_days": (q["earnings_date"] - hit["filed"]).days,
                    "peer_accn": hit["accessionNumber"],
                }
            )

    df = pd.DataFrame(rows).sort_values(["quarter", "ticker"])
    out = sc.PROCESSED / "hyperscaler_earnings_dates.csv"
    df.to_csv(out, index=False)

    pd.set_option("display.width", 200)
    print(f"\nWrote {out.relative_to(sc.REPO)}\n")
    print("Days by which each peer reports BEFORE Datadog, same calendar quarter:")
    print(
        df.groupby("ticker")["lead_days"]
        .agg(["median", "min", "max", "count"])
        .to_string()
    )
    late = df[df["lead_days"] <= 0]
    print(f"\nQuarters where the peer did NOT report before Datadog: {len(late)}")
    if len(late):
        print(late[["quarter", "ticker", "peer_earnings_date", "ddog_earnings_date", "lead_days"]].to_string(index=False))
    print("\nLast 8 quarters:")
    print(
        df[df["quarter"] >= sorted(df["quarter"].unique())[-8]]
        .pivot(index="quarter", columns="ticker", values="lead_days")
        .to_string()
    )


if __name__ == "__main__":
    main()
