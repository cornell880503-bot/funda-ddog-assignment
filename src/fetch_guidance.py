"""Build the guidance / customer-count entry template from Datadog's earnings
8-K press releases (Exhibit 99.1).

Guidance is not in XBRL. It has to come from the "Financial Outlook" section of
the quarterly press release. Rather than transcribing 28 filings by hand, this
script downloads each Item 2.02 8-K exhibit, caches it, and extracts the raw
sentences that contain outlook and customer-count language.

The output is a TEMPLATE, not a dataset. Every row carries the accession number
and the verbatim sentence it came from, so each number can be checked against
the filing before it is used. Nothing here is treated as final until the
`verified` column is set to yes in data/manual/guidance.csv.

Outputs:
  raw/8k_ex99_<accn>.txt                 cached exhibit text
  manual/guidance_template.csv           one row per guided quarter
  manual/customers_100k_template.csv     one row per reported quarter
"""

from __future__ import annotations

import argparse
import html
import re
import time

import pandas as pd
import requests

import sec_common as sc

CIK_INT = int(sc.CIK["DDOG"])

# Sentences that state forward revenue guidance. `(?:[^.]|\.\d)` keeps decimal
# points inside numbers from ending the sentence -- without it, guidance stated
# in billions ("Revenue between $1.19 billion and...") is truncated at "$1.".
SENT = r"(?:[^.]|\.\d)"
GUIDE_PAT = re.compile(
    rf"{SENT}*?(?:revenue between|revenue of \$|revenue in the range){SENT}*\.",
    re.IGNORECASE,
)
# Sentences that state the count of customers with ARR at or above $100k.
CUST_PAT = re.compile(rf"{SENT}*?\$100,?000{SENT}*\.", re.IGNORECASE)
MONEY_RANGE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)?\s*(?:to|and|-|–)\s*\$?\s?"
    r"([\d,]+(?:\.\d+)?)\s*(million|billion)?",
    re.IGNORECASE,
)


def strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def exhibit_text(accn: str, force: bool = False) -> str:
    """Fetch and cache the press-release exhibit text for one 8-K."""
    cache = sc.RAW / f"8k_ex99_{accn}.txt"
    if cache.exists() and not force:
        return cache.read_text()

    nodash = accn.replace("-", "")
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}/{nodash}/index.json"
    idx = requests.get(idx_url, headers=sc.HEADERS, timeout=60)
    time.sleep(sc.SLEEP_SECONDS)
    idx.raise_for_status()
    items = idx.json()["directory"]["item"]

    # Prefer the largest .htm exhibit that is not the 8-K cover document; the
    # press release is always the biggest attachment in these filings.
    candidates = [
        it
        for it in items
        if it["name"].lower().endswith((".htm", ".html"))
        and "index" not in it["name"].lower()
        and not it["name"].lower().endswith("-index.htm")
    ]
    candidates.sort(key=lambda it: int(it.get("size", 0)), reverse=True)
    if not candidates:
        return ""
    doc = candidates[0]["name"]
    url = f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}/{nodash}/{doc}"
    resp = requests.get(url, headers=sc.HEADERS, timeout=60)
    time.sleep(sc.SLEEP_SECONDS)
    resp.raise_for_status()
    text = strip_html(resp.text)
    cache.write_text(text)
    return text


def _to_musd(value: str, unit: str | None) -> float | None:
    if value is None:
        return None
    v = float(value.replace(",", ""))
    if unit and unit.lower() == "billion":
        return round(v * 1000, 3)
    if unit and unit.lower() == "million":
        return v
    # No unit attached to the first number of a range: it inherits the second.
    return v


def parse_guidance(text: str) -> dict:
    """Extract the next-quarter revenue guidance range, if stated plainly."""
    out = {"guide_sentence": None, "guide_low_musd": None, "guide_high_musd": None}
    window = text
    marker = re.search(r"financial outlook|business outlook", text, re.IGNORECASE)
    if marker:
        window = text[marker.start() : marker.start() + 4000]
    sentences = GUIDE_PAT.findall(window)
    if not sentences:
        return out
    sent = sentences[0].strip()
    out["guide_sentence"] = sent[:400]
    m = MONEY_RANGE.search(sent)
    if m:
        lo_v, lo_u, hi_v, hi_u = m.groups()
        hi = _to_musd(hi_v, hi_u)
        lo = _to_musd(lo_v, lo_u or hi_u)
        out["guide_low_musd"] = lo
        out["guide_high_musd"] = hi
    return out


def parse_customers(text: str) -> dict:
    out = {"customers_sentence": None, "customers_ge_100k": None}
    hits = CUST_PAT.findall(text)
    if not hits:
        return out
    sent = hits[0].strip()
    out["customers_sentence"] = sent[:400]
    m = re.search(r"([\d,]{3,6})\s+customers", sent)
    if not m:
        m = re.search(r"had\s+([\d,]{3,6})", sent)
    if m:
        out["customers_ge_100k"] = int(m.group(1).replace(",", ""))
    return out


def main(force: bool = False) -> None:
    quarters = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    quarters = quarters[quarters["known_from_reliable"]].dropna(subset=["earnings_accn"])

    rows = []
    for _, q in quarters.iterrows():
        accn = q["earnings_accn"]
        print(f"8-K {accn}  (reports {q['quarter']}, filed {q['earnings_date']})")
        try:
            text = exhibit_text(accn, force=force)
        except Exception as exc:  # keep going; a missing exhibit is not fatal
            print(f"  fetch failed: {exc}")
            text = ""
        rec = {
            "reported_quarter": q["quarter"],
            "issued_on": q["earnings_date"],
            "accession": accn,
            "url": q["earnings_url"],
        }
        rec.update(parse_guidance(text))
        rec.update(parse_customers(text))
        rows.append(rec)

    df = pd.DataFrame(rows)
    # Guidance issued alongside Q(t-1) results applies to Q(t).
    df["guided_quarter"] = (
        pd.PeriodIndex(df["reported_quarter"], freq="Q") + 1
    ).astype(str)

    guidance = df[
        [
            "guided_quarter",
            "reported_quarter",
            "issued_on",
            "guide_low_musd",
            "guide_high_musd",
            "guide_sentence",
            "accession",
            "url",
        ]
    ].copy()
    guidance["verified"] = ""
    guidance["notes"] = ""
    g_out = sc.MANUAL / "guidance_template.csv"
    guidance.to_csv(g_out, index=False)

    customers = df[
        [
            "reported_quarter",
            "issued_on",
            "customers_ge_100k",
            "customers_sentence",
            "accession",
            "url",
        ]
    ].copy()
    customers["verified"] = ""
    c_out = sc.MANUAL / "customers_100k_template.csv"
    customers.to_csv(c_out, index=False)

    n_g = guidance["guide_low_musd"].notna().sum()
    n_c = customers["customers_ge_100k"].notna().sum()
    print(f"\nWrote {g_out.relative_to(sc.REPO)}  ({n_g}/{len(guidance)} auto-extracted)")
    print(f"Wrote {c_out.relative_to(sc.REPO)}  ({n_c}/{len(customers)} auto-extracted)")
    print("\nEvery extracted number must be checked against its filing before use.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    main(**vars(ap.parse_args()))
