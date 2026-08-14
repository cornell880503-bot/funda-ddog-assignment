# ddog-nowcast

Alternative-data nowcasting of Datadog (NASDAQ: DDOG) quarterly results.

Two targets: quarterly revenue growth (`rev_yoy`) and revenue versus the
company's own guidance midpoint (`beat_vs_guide`). All data is public: SEC
EDGAR XBRL and press releases, the npm registry download API, and pypistats.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

SEC requires a contact email in the User-Agent. Set it before running:

```bash
export SEC_CONTACT_EMAIL="you@example.com"
```

## Pipeline

| Step | Command | Output |
|---|---|---|
| SEC targets | `python src/fetch_sec.py` | `data/processed/ddog_quarters.csv` |
| Guidance + customer counts | `python src/fetch_guidance.py` | `data/manual/*_template.csv` |
| npm downloads | `python src/fetch_npm.py` | `data/processed/npm_daily.csv`, `npm_qtd_pace.csv` |
| PyPI (180d only) | `python src/fetch_pypi.py` | `data/processed/pypi_daily_180d.csv` |
| Phase 1 checks | `python src/explore_phase1.py` | `report/figures/phase1_overview.png` |

Every fetcher caches its raw API response to `data/raw/` with a UTC timestamp
and reads the cache on subsequent runs; pass `--force` to re-pull. Analysis
code never calls an API.

## Data conventions that the analysis depends on

- **`known_from`** is the date a number became public — the earnings 8-K
  (Item 2.02) date where one can be matched, otherwise the 10-Q/10-K filing
  date. Every as-of feature is built against this column, not against period
  end and not against the XBRL `filed` field alone.
- **First print vs latest print.** `revenue_first_print` is what the market saw
  on the day; `revenue_latest_print` is the current value. Targets use the
  first print. `restated` flags any divergence (currently none).
- **Q4 is derived** as FY − (Q1+Q2+Q3) and inherits the 10-K's dates
  (`derived = True`).
- **`known_from_reliable = False`** marks pre-IPO quarters whose disclosure date
  cannot be trusted. They are valid YoY base values and invalid modelling rows.
- **Guidance and customer counts are unverified until reviewed.** Templates in
  `data/manual/` carry the parsed number, the verbatim source sentence, the
  accession number and the filing URL side by side.

See `LOG.md` for the decision record.
