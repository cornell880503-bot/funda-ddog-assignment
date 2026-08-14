"""Pull Datadog's XBRL company facts from SEC EDGAR and build the quarterly
target panel.

Outputs (all under data/):
  raw/sec_companyfacts_DDOG_<ts>.json   untouched API response
  raw/sec_submissions_DDOG_<ts>.json    untouched API response
  processed/ddog_quarters.csv           quarterly target panel
  processed/ddog_revenue_facts.csv      every revenue fact, all vintages
  processed/ddog_earnings_8k.csv        earnings press releases (Item 2.02)

Design notes that matter for the rest of the project:

* Every fact keeps its `filed` date -- the date the number became public. For
  each period we keep BOTH the earliest print (what the market saw first) and
  the latest print (restated value), so restatements are visible instead of
  silently overwriting history.
* 10-Qs give 3-month periods directly. Q4 is not filed as a 3-month period, so
  it is derived as FY minus Q1+Q2+Q3, inheriting the 10-K's filing date.
* The 10-Q/10-K filing date is NOT when the number became public. Datadog
  releases results in an 8-K (Item 2.02) a few days earlier. `known_from` uses
  the earnings 8-K date when one can be matched, and falls back to the
  10-Q/10-K filing date otherwise. As-of logic elsewhere uses `known_from`.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime

import pandas as pd

import sec_common as sc

REV_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",  # fallback for early filings
]
OTHER_TAGS = {
    "rpo_total": "RevenueRemainingPerformanceObligation",
    "deferred_rev_current": "ContractWithCustomerLiabilityCurrent",
    "deferred_rev_noncurrent": "ContractWithCustomerLiabilityNoncurrent",
    "deferred_rev_total": "ContractWithCustomerLiability",
}


def _d(x: str) -> date:
    return datetime.fromisoformat(x).date()


def _quarter_label(period_end: date) -> str:
    """Calendar quarter label. Datadog's fiscal year is the calendar year."""
    return f"{period_end.year}Q{(period_end.month - 1) // 3 + 1}"


def facts_frame(companyfacts: dict, tag: str) -> pd.DataFrame:
    """All USD facts for one us-gaap tag, one row per (period, filing)."""
    node = companyfacts["facts"].get("us-gaap", {}).get(tag)
    if node is None:
        return pd.DataFrame()
    rows = []
    for entry in node["units"]["USD"]:
        start = _d(entry["start"]) if "start" in entry else None
        end = _d(entry["end"])
        rows.append(
            {
                "tag": tag,
                "start": start,
                "end": end,
                "duration_days": (end - start).days + 1 if start else None,
                "val": entry["val"],
                "form": entry["form"],
                "fy": entry.get("fy"),
                "fp": entry.get("fp"),
                "filed": _d(entry["filed"]),
                "accn": entry["accn"],
                "frame": entry.get("frame"),
            }
        )
    return pd.DataFrame(rows)


def revenue_facts(companyfacts: dict) -> pd.DataFrame:
    frames = [facts_frame(companyfacts, t) for t in REV_TAGS]
    frames = [f for f in frames if not f.empty]
    df = pd.concat(frames, ignore_index=True)
    # Prefer the ASC 606 tag when both exist for the same period+filing.
    df["tag_rank"] = df["tag"].map({t: i for i, t in enumerate(REV_TAGS)})
    df = df.sort_values(["end", "start", "filed", "tag_rank"]).reset_index(drop=True)
    return df


def earnings_8k(submissions: dict) -> pd.DataFrame:
    """8-K filings reporting results of operations (Item 2.02).

    These are the earnings press releases (Exhibit 99.1) and their filing date
    is the date the quarter's numbers and the next quarter's guidance became
    public.
    """
    recent = submissions["filings"]["recent"]
    df = pd.DataFrame(
        {
            "form": recent["form"],
            "filed": recent["filingDate"],
            "accn": recent["accessionNumber"],
            "items": recent["items"],
            "primary_doc": recent["primaryDocument"],
        }
    )
    older = submissions["filings"].get("files", [])
    for chunk in older:
        payload = sc.get_json(
            f"https://data.sec.gov/submissions/{chunk['name']}",
            f"sec_submissions_chunk_{chunk['name'].replace('.json','')}",
        )
        df = pd.concat(
            [
                df,
                pd.DataFrame(
                    {
                        "form": payload["form"],
                        "filed": payload["filingDate"],
                        "accn": payload["accessionNumber"],
                        "items": payload["items"],
                        "primary_doc": payload["primaryDocument"],
                    }
                ),
            ],
            ignore_index=True,
        )
    df = df[(df["form"] == "8-K") & (df["items"].str.contains("2.02", na=False))].copy()
    df["filed"] = pd.to_datetime(df["filed"]).dt.date
    df["url"] = [sc.filing_index_url(sc.CIK["DDOG"], a) for a in df["accn"]]
    return df.sort_values("filed").reset_index(drop=True)


def build_quarters(rev: pd.DataFrame) -> pd.DataFrame:
    """Quarterly revenue panel with first-print and latest-print vintages."""
    q = rev[(rev["duration_days"] >= 80) & (rev["duration_days"] <= 100)].copy()
    fy = rev[(rev["duration_days"] >= 355) & (rev["duration_days"] <= 375)].copy()

    def collapse(df: pd.DataFrame) -> pd.DataFrame:
        first = df.sort_values("filed").groupby("end", as_index=False).first()
        last = df.sort_values("filed").groupby("end", as_index=False).last()
        out = first[["end", "start", "val", "form", "filed", "accn"]].rename(
            columns={
                "val": "revenue_first_print",
                "form": "first_form",
                "filed": "first_filed",
                "accn": "first_accn",
            }
        )
        out["revenue_latest_print"] = last["val"].values
        out["latest_filed"] = last["filed"].values
        out["n_vintages"] = df.groupby("end")["filed"].nunique().values
        return out

    qq = collapse(q)
    qq["derived"] = False

    # Derive Q4 = FY - (Q1 + Q2 + Q3), inheriting the 10-K filing date.
    fy_first = fy.sort_values("filed").groupby("end", as_index=False).first()
    derived_rows = []
    for _, row in fy_first.iterrows():
        year = row["end"].year
        prior = qq[(qq["end"].map(lambda e: e.year) == year)]
        prior = prior[prior["end"].map(lambda e: e.month) != 12]
        if len(prior) != 3:
            continue
        q4_val = row["val"] - prior["revenue_first_print"].sum()
        fy_last = (
            fy[fy["end"] == row["end"]].sort_values("filed").iloc[-1]
        )
        prior_last = qq[
            (qq["end"].map(lambda e: e.year) == year)
            & (qq["end"].map(lambda e: e.month) != 12)
        ]["revenue_latest_print"].sum()
        derived_rows.append(
            {
                "end": row["end"],
                "start": date(year, 10, 1),
                "revenue_first_print": q4_val,
                "first_form": row["form"],
                "first_filed": row["filed"],
                "first_accn": row["accn"],
                "revenue_latest_print": fy_last["val"] - prior_last,
                "latest_filed": fy_last["filed"],
                "n_vintages": fy[fy["end"] == row["end"]]["filed"].nunique(),
                "derived": True,
            }
        )
    out = pd.concat([qq, pd.DataFrame(derived_rows)], ignore_index=True)
    out = out.sort_values("end").reset_index(drop=True)
    out["quarter"] = out["end"].map(_quarter_label)
    out["restated"] = out["revenue_first_print"] != out["revenue_latest_print"]
    return out


def attach_earnings_dates(quarters: pd.DataFrame, eps: pd.DataFrame) -> pd.DataFrame:
    """Match each quarter to the earnings 8-K that first disclosed it.

    Rule: the earliest Item 2.02 8-K filed after the period end and on or
    before the 10-Q/10-K filing date for that period.
    """
    earn_date, earn_accn, earn_url = [], [], []
    for _, row in quarters.iterrows():
        cand = eps[(eps["filed"] > row["end"]) & (eps["filed"] <= row["first_filed"])]
        if len(cand):
            hit = cand.iloc[0]
            earn_date.append(hit["filed"])
            earn_accn.append(hit["accn"])
            earn_url.append(hit["url"])
        else:
            earn_date.append(pd.NaT)
            earn_accn.append(None)
            earn_url.append(None)
    out = quarters.copy()
    out["earnings_date"] = earn_date
    out["earnings_accn"] = earn_accn
    out["earnings_url"] = earn_url
    out["known_from"] = [
        e if pd.notna(e) else f for e, f in zip(out["earnings_date"], out["first_filed"])
    ]
    out["report_lag_days_filing"] = [
        (f - e).days for f, e in zip(out["first_filed"], out["end"])
    ]
    out["report_lag_days_known"] = [
        (k - e).days for k, e in zip(out["known_from"], out["end"])
    ]
    return out


def attach_balance_items(quarters: pd.DataFrame, cf: dict) -> pd.DataFrame:
    """Attach point-in-time balance-sheet style items (RPO, deferred revenue).

    These are instant facts (no start date); we take the first print for each
    period end so the vintage matches the revenue first print.
    """
    out = quarters.copy()
    for name, tag in OTHER_TAGS.items():
        df = facts_frame(cf, tag)
        if df.empty:
            out[name] = pd.NA
            continue
        inst = df[df["start"].isna()].copy()
        if inst.empty:
            inst = df.copy()
        first = inst.sort_values("filed").groupby("end", as_index=False).first()
        out = out.merge(
            first[["end", "val", "filed"]].rename(
                columns={"val": name, "filed": f"{name}_filed"}
            ),
            on="end",
            how="left",
        )
    return out


def main(force: bool = False) -> None:
    print("Fetching SEC data for DDOG ...")
    cf = sc.companyfacts("DDOG", force=force)
    subs = sc.submissions("DDOG", force=force)

    rev = revenue_facts(cf)
    rev.to_csv(sc.PROCESSED / "ddog_revenue_facts.csv", index=False)

    eps = earnings_8k(subs)
    eps.to_csv(sc.PROCESSED / "ddog_earnings_8k.csv", index=False)

    quarters = build_quarters(rev)
    quarters = attach_earnings_dates(quarters, eps)
    quarters = attach_balance_items(quarters, cf)

    # Growth targets computed on the FIRST PRINT, which is what was known at
    # the time. YoY must be matched on the calendar quarter, not on row
    # position: the XBRL history has gaps before the IPO, so a positional
    # .pct_change(4) would silently compare mismatched quarters.
    quarters = quarters.sort_values("end").reset_index(drop=True)
    quarters["revenue_musd"] = quarters["revenue_first_print"] / 1e6
    period = pd.PeriodIndex(pd.to_datetime(quarters["end"]), freq="Q")
    rev_by_q = pd.Series(quarters["revenue_first_print"].values, index=period)
    full = rev_by_q.reindex(pd.period_range(period.min(), period.max(), freq="Q"))
    quarters["rev_yoy"] = (full / full.shift(4) - 1).reindex(period).values
    quarters["rev_qoq"] = (full / full.shift(1) - 1).reindex(period).values

    # Flag quarters whose first public disclosure date cannot be trusted.
    # Pre-IPO quarters only entered XBRL through later comparatives, so the
    # matched 8-K is not the release that first made them public.
    quarters["known_from_reliable"] = quarters["report_lag_days_known"].between(25, 60)

    cols = [
        "quarter",
        "start",
        "end",
        "revenue_musd",
        "rev_yoy",
        "rev_qoq",
        "earnings_date",
        "first_filed",
        "known_from",
        "known_from_reliable",
        "report_lag_days_known",
        "report_lag_days_filing",
        "derived",
        "first_form",
        "restated",
        "n_vintages",
        "revenue_first_print",
        "revenue_latest_print",
        "rpo_total",
        "deferred_rev_current",
        "deferred_rev_noncurrent",
        "earnings_accn",
        "first_accn",
        "earnings_url",
    ]
    quarters = quarters[[c for c in cols if c in quarters.columns]]
    out_path = sc.PROCESSED / "ddog_quarters.csv"
    quarters.to_csv(out_path, index=False)
    print(f"\nWrote {out_path.relative_to(sc.REPO)}  ({len(quarters)} quarters)")

    rel = quarters[quarters["known_from_reliable"]]
    print("\nReport lag, period end -> earnings release (reliable quarters only), days:")
    print(rel["report_lag_days_known"].describe().round(1).to_string())
    print("\nBy fiscal quarter (median days):")
    print(
        rel.assign(fq=rel["quarter"].str[-2:])
        .groupby("fq")["report_lag_days_known"]
        .agg(["median", "min", "max", "count"])
        .to_string()
    )
    print("\nEarnings 8-K -> 10-Q/10-K filing gap, days:")
    gap = (
        pd.to_datetime(rel["first_filed"]) - pd.to_datetime(rel["earnings_date"])
    ).dt.days
    print(gap.describe().round(1).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-pull instead of using cache")
    main(**vars(ap.parse_args()))
