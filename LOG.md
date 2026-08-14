# Decisions log

Running record of non-obvious decisions, why they were made, and what was
rejected. Q&A will probe judgement calls; this is the reconstruction.

---

## Phase 1 — Data (2026-08-14)

### D1. Public-disclosure date is the earnings 8-K, not the 10-Q filing date
The first-pass script used the XBRL `filed` field (the 10-Q/10-K date) as the
moment a number became public. That is wrong: Datadog releases results in an
8-K under Item 2.02 first. Measured across 28 quarters, the 8-K precedes the
10-Q by a median of 1 day, but for Q4 the gap runs up to 18 days (2025Q4:
8-K 2026-02-10, 10-K 2026-02-18). Using the 10-K date would have let a Q4
model see Q4's own number as if it were still unknown for two extra weeks, and
would have mis-dated every guidance observation.
Panel now carries `earnings_date`, `first_filed`, and `known_from`
(= earnings date where matched, filing date otherwise). All as-of logic uses
`known_from`.
**Rejected:** assuming a fixed 35- or 45-day reporting lag. Actual lag is 34–47
days and is systematically longer for Q4 (median 44 vs 36–38 for Q1–Q3), which
matters for the Q4 nowcast horizon.

### D2. Year-over-year must be matched on calendar quarter, not row position
`pct_change(4)` on the assembled panel is wrong because the XBRL history has
gaps before the IPO (2018Q3 exists, 2018Q4 and 2019Q1–Q2 come from later
comparatives). Positionally, 2019Q4 was being divided by 2018Q3, producing a
fake 122.5% growth print. Fixed by reindexing on a `PeriodIndex` so the shift
is calendar-correct. Quarters that cannot form a YoY are `NaN`, not invented.

### D3. Keep first print and latest print, not just the first
Every period keeps `revenue_first_print` (earliest filing = what the market
saw) and `revenue_latest_print` (most recent filing), plus `n_vintages` and a
`restated` flag. Result: Datadog has never restated quarterly revenue in this
history (`restated` is False for all 31 quarters), so first-print and
latest-print modelling are identical here — but the check is now explicit
rather than assumed, and the panel would surface a restatement if one appeared.
All growth targets are computed on the **first print**.

### D4. Q4 derived as FY − (Q1+Q2+Q3), inheriting the 10-K's filing date
XBRL does not publish a 3-month Q4 fact. Derivation uses first prints for
Q1–Q3 and the FY total. `derived` flags these rows. Cross-check: derived 2025Q4
= $953.194m; FY2025 = sum of four quarters, consistent by construction, and
the YoY series shows no discontinuity at Q4 boundaries.

### D5. Pre-IPO quarters flagged rather than dropped
2018Q3, 2019Q1 and 2019Q2 entered XBRL only via later comparatives, so the
matched 8-K is not the release that first made them public (implied lags of
408, 226 and 135 days). They carry `known_from_reliable = False`. They are kept
for YoY base values but must never be used as modelling observations.
28 quarters have a trustworthy disclosure date (2019Q3 → 2026Q2).

### D6. Guidance auto-extracted from 8-K Exhibit 99.1, then verified by hand
The brief called for hand entry. Instead each Item 2.02 8-K exhibit is
downloaded, cached to `data/raw/8k_ex99_<accn>.txt`, and the outlook sentence
is regex-extracted verbatim into the template alongside the accession number
and filing URL. 28/28 quarters extracted. This is not a shortcut around the
rigour requirement: the template keeps the source sentence next to the parsed
number and a `verified` column, so review is a comparison rather than a
transcription. **Numbers are not final until `verified` is filled in.**
One parsing trap found and fixed: a naive sentence split on `.` truncates
guidance stated in billions ("Revenue between $1." ), which silently dropped
the two most recent and most important quarters.

### D7. Customer counts (ARR ≥ $100k) extracted the same way
Not in XBRL. 28/28 quarters extracted from the press-release highlights
section, e.g. 2026Q2: "about 4,720 customers with ARR of $100,000 or more, an
increase of 23% from about 3,850". Note the company reports these as "about"
figures rounded to the nearest ten, which caps the precision of any
customer-count target.

### D8. npm control cohort expanded, and it already changed a conclusion
Controls are `@opentelemetry/api`, `newrelic`, `elastic-apm-node`, plus
`@sentry/node` (added: adjacent observability vendor with a large JS install
base). Datadog packages gained `@datadog/datadog-ci`.
**This is the most important Phase 1 finding.** Datadog npm downloads grew
+92% YoY in 2026Q1 and +112% in 2026Q2, which looks like a spectacular
confirmation of the revenue acceleration — until the control cohort is checked:
controls grew +102% and +184% over the same quarters. Datadog's *share* of
tracked instrumentation downloads has fallen from 29.4% (2024Q2) to 21.4%
(2026Q2). The 2026 download surge is ecosystem-wide, not Datadog-specific.
An absolute-download model would have read this as a bullish Datadog signal;
it is mostly registry/CI inflation.
**Open question for Phase 3:** the control cohort is dominated by
`@opentelemetry/api` (~10.1m downloads/day vs ~3.5m/day for all Datadog
packages), and OpenTelemetry is partly complementary to Datadog rather than
competitive — Datadog ingests OTel telemetry. A share metric against a
competitor-only denominator (`newrelic`, `elastic-apm-node`) may be the more
meaningful construction. Both will be tested, and the choice logged.

### D9. PyPI: 180-day window only, pending a decision on BigQuery
`pypistats.org` returns 181 days (2026-02-14 → 2026-08-13), which is not enough
to fit or validate anything over 8–12+ quarters. Pulled anyway as a
recent-period cross-check on the npm signal, and the `without_mirrors`
category is used to strip known mirror traffic. Full history needs
`bigquery-public-data.pypi.file_downloads`, which requires a GCP project with
billing. **Blocked on user confirmation** — the BigQuery code path raises
rather than silently doing something else.

### D10. Everything cached, nothing re-pulled inside analysis
All API responses land in `data/raw/` with a UTC timestamp in the filename;
fetchers read the newest cached copy unless `--force`. Analysis code reads only
`data/processed/`. SEC calls carry a descriptive User-Agent with a contact
email and sleep 0.25s (limit is 10 req/s).

### Smell test (not a result)
Contemporaneous correlation between full-quarter Datadog npm YoY and revenue
YoY is 0.786 over 27 quarters. This uses the whole quarter of downloads,
including days after quarter close, so it is not usable as a signal and is
recorded only as a reason to continue. Lead–lag and partial-quarter tests
decide whether anything here is real.

### Target variables as of Phase 1
- `rev_yoy`: 24.6% (2025Q1) → 35.6% (2026Q2). The structural break in §5.5 of
  the brief is confirmed in the SEC data, not taken on trust.
- `beat_vs_guide`: 27 usable quarters, mean +6.03%, median +4.79%, sd 2.88pp,
  **0 quarters below the guidance midpoint**. Last 8 quarters mean +4.25%,
  which is the relevant base rate. 2026Q2 beat the midpoint by +4.32%.
- Live target: 2026Q3 guidance is $1.135bn–$1.145bn (midpoint $1.140bn),
  issued 2026-08-06.
