"""Shared helpers for SEC EDGAR access.

SEC requires a descriptive User-Agent with a contact email or it returns 403.
Rate limit is 10 requests/second; we sleep conservatively between calls and
cache every raw response to data/raw/ so analysis code never re-pulls.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
PROCESSED = REPO / "data" / "processed"
MANUAL = REPO / "data" / "manual"

CONTACT_EMAIL = os.environ.get("SEC_CONTACT_EMAIL", "cornell880503@gmail.com")
USER_AGENT = f"DDOG-Nowcast research project ({CONTACT_EMAIL})"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# CIKs used across the project.
CIK = {
    "DDOG": "0001561550",
    "AMZN": "0001018724",  # AWS segment
    "MSFT": "0000789019",  # Intelligent Cloud segment
    "GOOGL": "0001652044",  # Google Cloud segment
    "SNOW": "0001640147",
    "MDB": "0001441816",
    "NET": "0001477333",
}

SLEEP_SECONDS = 0.25  # well inside SEC's 10 req/s limit


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def get_json(url: str, cache_name: str, force: bool = False) -> dict:
    """GET a JSON endpoint and cache the untouched response to data/raw/.

    cache_name is the logical name; the file written is
    data/raw/<cache_name>_<utc timestamp>.json. If a cached copy already
    exists and force is False, the most recent cached copy is returned and no
    network call is made.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    existing = sorted(RAW.glob(f"{cache_name}_*.json"))
    if existing and not force:
        with open(existing[-1]) as fh:
            return json.load(fh)

    resp = requests.get(url, headers=HEADERS, timeout=90)
    time.sleep(SLEEP_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    out = RAW / f"{cache_name}_{utc_stamp()}.json"
    with open(out, "w") as fh:
        json.dump(payload, fh)
    print(f"  cached {out.relative_to(REPO)} ({out.stat().st_size/1e6:.1f} MB)")
    return payload


def companyfacts(ticker: str, force: bool = False) -> dict:
    cik = CIK[ticker]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return get_json(url, f"sec_companyfacts_{ticker}", force=force)


def submissions(ticker: str, force: bool = False) -> dict:
    cik = CIK[ticker]
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return get_json(url, f"sec_submissions_{ticker}", force=force)


def filing_index_url(cik: str, accession: str) -> str:
    accn_nodash = accession.replace("-", "")
    cik_int = int(cik)
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/"
        f"{accession}-index.htm"
    )
