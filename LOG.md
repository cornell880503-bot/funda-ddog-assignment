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

### D11. Denominator decided a priori on economic grounds — and OpenTelemetry is disqualified on evidence
Decision rule: the control basket is chosen **before** looking at out-of-sample
performance. With roughly 10 out-of-sample points, selecting the feature
definition on test-set results contaminates the validation, and the resulting
hit rate would not mean anything.

**Empirical check that settles it.** Querying the npm registry metadata:
`dd-trace` declares `@opentelemetry/api` as a *direct dependency* from v4.2.0
(released 2023-06-13) through v5.80.0 (2025-11-21). v6, released 2026-07-02,
drops it. As of this week, **82.6% of dd-trace downloads are still v5**
(8.28m of 10.03m weekly), with v6 at 12.9%. So for most of the sample window a
`dd-trace` install also pulls `@opentelemetry/api` from the registry.
A denominator containing `@opentelemetry/api` therefore contains traffic
generated by the numerator. Upper-bound magnitude: dd-trace runs ~1.27m
downloads/day against ~10.1m/day for `@opentelemetry/api`, so up to roughly
10% of the OTel series could be dd-trace-induced (an upper bound — lockfiles
and local caches mean not every install triggers a registry fetch).
**`@opentelemetry/api` is excluded from the primary denominator outright.**

**Primary feature is a difference, not a ratio.** Both candidate ratios have a
mechanical defect: OTel is large and growing, which suppresses the share by
construction, while `newrelic` and `elastic-apm-node` are shrinking, which
inflates it. A ratio is sensitive to the denominator's *level*; a difference in
YoY log growth is not. Primary feature:

    dd_rel_growth(t) = Δlog(Datadog basket, YoY) − Δlog(control basket, YoY)

Control basket = `newrelic` + `elastic-apm-node`, on the economic ground that
they are **substitutes** for Datadog, whereas OpenTelemetry is largely
**complementary** (Datadog ingests OTel telemetry, so OTel growth is not
Datadog share loss).

**Also carried, separately:** absolute Datadog YoY log growth, as its own
candidate feature. If the absolute and relative features disagree materially,
that disagreement is a finding and gets a paragraph, not a silent tiebreak.

**Robustness only, in the appendix:** the OTel-inclusive version, explicitly
labelled a sensitivity test and never used for feature selection.

**Rejected:** (a) picking the denominator by out-of-sample score — contaminates
validation; (b) share-of-total including OTel as primary — fails the dependency
check above; (c) competitor-only *ratio* rather than difference — the
denominator is shrinking, which mechanically inflates the ratio's trend.

### D12. Guidance audit: A, B and D pass on all 28 quarters; C flags real economics
Audit checks (`src/audit_guidance.py`), thresholds stated rather than tuned:
- **A, range width / midpoint:** all 28 rows between 0.44% and 1.96%
  (median 0.87%). No zero-width or absurd ranges → no wrong-number-pair parses.
- **B, actual below midpoint:** zero rows. Consistent with 27 straight beats.
- **D, issue date vs SEC earnings date:** zero mismatches across all 28 rows.
  Guidance for Q(t) is issued exactly on the Q(t−1) earnings date, confirmed
  against filing data rather than assumed.
- **C, midpoint-implied YoY jump > 10pp:** 4 rows — 2021Q3, 2022Q3, 2022Q4,
  2023Q1. These sit precisely in the 2021–2023 deceleration (growth fell from
  ~83% to ~33% YoY), so the check is picking up genuine economics, not
  misparses. They still go on the manual worklist; the interpretation is
  recorded here so the check is quick.

Worklist = last 8 quarters ∪ all flagged rows = 12 rows
(`data/manual/verification_worklist.csv`). Rows that cannot be confirmed from
the primary document get **dropped, not kept**. Phase 2 proceeds on unverified
values, and **no final number is produced until the verified set lands**.

### D13. PyPI scoped as a cross-ecosystem robustness check, not a model input
No BigQuery project, so no long PyPI history. The 181-day window is used for
one specific purpose: showing that `ddtrace` (PyPI) and `dd-trace` (npm) move
in the same direction over the overlapping period, i.e. the npm signal is not
a JavaScript-ecosystem artefact. Note that a true YoY is not computable from
181 days, so the check is on within-window growth and on the co-movement of
weekly log changes, and is reported as such. Part 1's data table will state
plainly that PyPI long history requires BigQuery and was out of scope.

### D14. NEGATIVE RESULT — the PyPI cross-ecosystem check does not confirm the npm signal
Two tests were run over the 181-day overlap (2026-02-14 → 2026-08-13). Both
fail, and both are reported.

*All figures below use the causal (as-of legal) imputation of D16. The raw and
centred variants give materially different numbers; that spread is reported as
a sensitivity finding in D16b rather than resolved silently.*

**Test 1, co-movement of weekly log changes: inconclusive, and dropped.**
`dd-trace` (npm) correlates with `ddtrace` (PyPI) at 0.972 on weekly log
changes. The placebo: `newrelic` reaches 0.961 and `elastic-apm-node` 0.932 —
every package tested, competitor or not, sits in a narrow 0.93–0.98 band.
A bootstrap on the *difference* between the Datadog correlation and the best
control correlation (10,000 resamples of the 26 aligned weeks, seed 20260814)
gives a 95% CI of **[−0.010, +0.726]**, which covers zero.
Note also that sign agreement is only 54–62% despite correlations above 0.93 —
the tell that a large shared seasonal component is inflating the correlation
while the residual direction is near a coin flip.
The correlation level measures a shared working-day and holiday calendar. The
test cannot support a Datadog-specific claim in either direction and is not
used as evidence. **Reporting a cross-registry correlation without a placebo
would have been a false positive; the ranking on its own is noise at n=26.**

**Test 2, relative growth (calendar effect differenced out): opposite signs.**

| registry | Datadog basket | substitute controls | excess |
|---|---|---|---|
| npm | +37.8% | +9.9% | **+27.9pp** |
| PyPI | +10.3% | +26.2% | **−15.8pp** |

Like-for-like, tracer against New Relic's agent in the same registry: npm
`dd-trace` +63.5% vs `newrelic` +10.1% (+53.4pp); PyPI `ddtrace` +21.4% vs
`newrelic` +40.8% (−19.5pp). Datadog outgrows its controls on npm and
underperforms them on PyPI over the identical window.

Caveats that limit how much weight this negative carries — all of them stated
in the report rather than used to explain it away: the PyPI control base is
small (`newrelic` ~135k downloads/day against 1.27m/day for `ddtrace`), so its
growth rate is volatile; the largest PyPI "Datadog" package by volume is
`datadog` (2.27m/day), an API/metrics client rather than instrumentation, which
drags the basket; and 181 days is one short window with no YoY available.

**This is a failed confirmation, not a refutation, and it is a low-power one.**
With 181 days there is no YoY available and the test had little power to begin
with. It does not show the npm signal is wrong; it shows the npm signal is not
independently corroborated by the only other ecosystem observable for free.
**Reporting treatment:** one line in the Part 1 data table — cross-ecosystem
confirmation was attempted, the available window was underpowered, and Signal 1
therefore rests on the npm ecosystem alone. A low-power null is not inflated
into evidence against the signal, and it does not go in the headline. This is a
different and much smaller issue than the placebo design in D17.

### D15. Hyperscaler timing verified — and the assumed lead is wrong
The brief states Amazon reports "roughly two weeks" before Datadog. Checked
against Item 2.02 8-K filing dates for all 28 quarters:

| peer | median lead over DDOG | min | max | quarters where peer reported first |
|---|---|---|---|---|
| AMZN | **7 days** | 5 | 19 | 28 / 28 |
| GOOGL | 9.5 days | 6 | 16 | 28 / 28 |
| MSFT | 10.5 days | 6 | 23 | 28 / 28 |

The *direction* holds without exception — all three hyperscalers report before
Datadog in every quarter on record, so this is a genuine information lead and
usable in the as-of panel. The *magnitude* in the brief is roughly double the
truth: Amazon's recent lead is 5–8 days, not fourteen. Operationally this
narrows the actionable window: the hyperscaler read lands about a week before
Datadog prints, not two. Assuming fourteen days would have put look-ahead bias
into every quarter where the real gap was five.

Segment revenue values are a separate problem: the XBRL `companyfacts` endpoint
returns **consolidated facts only** and drops the dimensional (segment) axis, so
AWS / Intelligent Cloud / Google Cloud revenue cannot be pulled from it. Those
values have to come from the press releases, handled the same way as Datadog's
guidance (auto-extract, cache, verify against the primary document).

### D16. npm data quality — 12 registry-wide missing days, 4 of them in the live quarter
The npm downloads API returns 0, or a small fraction of normal volume, for
*every* package on certain dates. These are API gaps, not days on which nobody
installed software. 12 such days in 3,512, found by flagging any date whose
cross-package total falls below 20% of its centred 7-day median.

| date | packages affected | raw total | imputed total |
|---|---|---|---|
| 2026-08-13 | 13 | 0 | 181.5m |
| 2026-07-26 | 13 | 36.0m | 78.7m |
| 2026-07-12 | 13 | 0 | 78.2m |
| 2026-07-09 | 13 | 29.8m | 174.9m |

…plus 8 earlier dates (2018-05-26/27, 2020-06-22, 2022-05-08, 2022-07-22,
2023-11-03, 2025-10-21, 2026-06-03).

**Four of the twelve fall inside 2026Q3 — the quarter being nowcast — out of
roughly 44 elapsed days.** 2026-08-13, a total zero, is the most recent day
available. Uncorrected, these would have dragged the live quarter-to-date pace
down by roughly 9% of the quarter's observations and produced a spuriously
bearish headline call.

**Two imputation variants, and they are not interchangeable.**

| variant | window | used by |
|---|---|---|
| `imputed_causal` | same weekday, **prior 42 days only** | as-of panel, walk-forward, live QTD estimate — the only variant on a feature path |
| `imputed_centered` | same weekday, ±21 days | descriptive charts and the data-quality appendix **only** |

A centred fill uses days *after* the gap, so the value could not have been
known on the date it occupies. That is look-ahead bias by construction, however
small, and it is exactly the failure mode §4 of the brief exists to prevent.
`load_centered()` tags its output with `forbidden_on_feature_path`, and
`tests/test_asof.py` asserts that building the panel never touches it.

Weekday matching (rather than plain interpolation) is used in both, because
downloads have a strong day-of-week profile — weekday CI builds dominate — so
interpolating across a Monday gap systematically under-fills it.

Causal fills come in 2–12% **below** centred fills on the same days, because
backward-only medians lag a growing series. That is the conservative direction
for a live nowcast, which is the right way for the error to point.

`express` is dropped entirely: the API returns 1,734 consecutive zero days
before 2021-10-01 for a package that was in heavy use throughout. Package-level
defect, not a gap to patch.

### D16a. The outage rule was fixed before its effect was known — precisely what the git history does and does not establish
This matters because "clean the data until the correlation improves" is exactly
the failure the rule must not be suspected of. Stating the evidence exactly:

**What the history proves.** Commit `0d4427f` records the *unfavourable*
pre-cleaning result in LOG.md — `dd-trace` at 0.932, **below** the `newrelic`
placebo at 0.951 — and contains no cleaning code at all (`src/` at that commit
has no `npm_clean.py`). The result that cuts against the signal was committed
first, before any cleaning existed.

**What the history does not prove.** The detection rule and the recomputed
correlation landed together in commit `a505a22`. So the commits alone do not
independently establish that the 20% threshold was fixed *before* the flip was
observed, even though that is the order in which the work happened.

**What supports it beyond the ordering.** The threshold has a single value,
`BAD_DAY_THRESHOLD = 0.20`, introduced once and never edited since
(`git log -p src/npm_clean.py` shows no change to it). No alternative threshold
was tried. The rule is also stated in terms that are independent of any
correlation: a date is invalid if the *cross-package* total falls below 20% of
its centred 7-day median, which is a statement about the registry API, not
about Datadog.

I will present it at this level of precision rather than claiming
pre-registration I cannot demonstrate.

### D16b. The before/after is a sensitivity finding, not a repair
Correlation of `dd-trace` with PyPI `ddtrace`, weekly log changes, n=26:

| treatment | dd-trace | best placebo (`newrelic`) | above placebo? |
|---|---|---|---|
| raw, outage zeros left in | 0.932 | 0.951 | **no** |
| causal (as-of legal, **reported**) | **0.972** | 0.961 | yes |
| centered (descriptive) | 0.975 | 0.961 | yes |

**Removing 0.34% of observations moves the correlation from below placebo to
above it.** That fragility is the finding. A result that flips sign on twelve
days out of 3,512 cannot support a conclusion in either direction, and the
report presents this as **evidence for the inconclusive verdict**, not as a
repair that rescued the signal. The bootstrap CI on the Datadog-minus-placebo
gap covers zero under all three treatments independently
(causal: [−0.010, +0.726]; raw: [−0.048, +0.343]).

The reported number is the causal one, **0.972**, not 0.975.

### D17. Placebo runs the full pipeline, not just a correlation
A placebo that only appears in a correlation table, while the main body claims
a working signal, is internally inconsistent. So the negative control gets
identical treatment to the real signal: same feature construction, same as-of
vintage rules, same walk-forward, same error metrics against the same
baselines.

Placebo basket: `lodash`, `chalk`, `axios`, `react` — general-purpose
JavaScript utilities with **no economic link to Datadog's revenue**. (`express`
dropped per D16.) Features built from them:
`placebo_abs` = YoY log growth of the placebo basket, and
`placebo_rel` = `placebo_abs` − control-basket YoY log growth — the exact
construction used for the real feature.

The two outcomes are pre-committed here so the framing is not chosen after
seeing the result:
- **If the placebo also beats AR(1) out of sample** → the signal is not real.
  That goes in the page-1 conclusion, not an appendix. The deliverable becomes
  "a signal with a plausible economic story that does not survive validation,
  and the method that established it" — a legitimate result given the
  assignment's explicit request for honest interpretation.
- **If the placebo fails out of sample while the Datadog feature survives** →
  the placebo has strengthened the case, by showing the raw correlation was
  trend-driven and that the difference-in-log-growth construction removes the
  spurious component. That goes in **Methodology as evidence design**, not in
  Limitations.

Either way the placebo design and its result appear in the main body; detailed
tables go to the appendix.

### Target variables as of Phase 1
- `rev_yoy`: 24.6% (2025Q1) → 35.6% (2026Q2). The structural break in §5.5 of
  the brief is confirmed in the SEC data, not taken on trust.
- `beat_vs_guide`: 27 usable quarters, mean +6.03%, median +4.79%, sd 2.88pp,
  **0 quarters below the guidance midpoint**. Last 8 quarters mean +4.25%,
  which is the relevant base rate. 2026Q2 beat the midpoint by +4.32%.
- Live target: 2026Q3 guidance is $1.135bn–$1.145bn (midpoint $1.140bn),
  issued 2026-08-06.

---

## Phase 2 — As-of panel (2026-08-14)

### D18. Features are stored as vintages, not as a wide table
The panel is `(quarter, feature, value, available_from)`, one row per vintage,
and `features_asof(quarter, asof)` is a filter over `available_from`. Asking
"what could I have known" is then a query, not a judgement call made per model.
1,106 vintage rows, 34 features, 35 quarters.

`available_from` by source:
- npm: `quarter_start + h days + 1 day` of API latency. The one-day latency is
  verified, not assumed — the API's most recent available day is D−1.
- DDOG revenue: `known_from` (the earnings 8-K date, per D1).
- DDOG guidance: `issued_on` (the prior quarter's earnings call, per D12 check D).
- hyperscalers: the peer's own Item 2.02 8-K date (per D15).

Three decision rules are supported: `day30/45/60` (mid-quarter, still
actionable), `quarter_end`, and `pre_earnings` (the day before Datadog
reports). Feature counts per quarter: 19 at day 45, 31 at quarter end, 34
pre-earnings — the panel gets richer as the quarter progresses, which is the
whole point of the partial-quarter design.

### D19. 13 as-of tests, and what each one would have caught
`tests/test_asof.py`, all passing. Beyond the headline assertion, each test
targets a specific way the bias gets in:
- **no feature dated after its as-of** — the core guarantee, checked across
  every quarter × all five decision rules.
- **monotonicity** — a later as-of date may add features but never change a
  value already visible. Catches silent restatement of a feature.
- **partial-quarter timing** — `dd_rel_d45` must not exist on day 44, and must
  exist on day 46.
- **full-quarter feature at quarter close** — must still be illegal on the
  closing day itself, because of the one-day API latency.
- **guidance not available the day before it was issued** — checked for all 28
  guidance rows individually.
- **lagged revenue dated by the 8-K** — asserts `rev_yoy_lag1`'s
  `available_from` equals the prior quarter's `known_from` exactly, and that it
  is strictly after the prior quarter's period end. This is the test that would
  have caught the original `filed`-vs-8-K error in D1.
- **centred imputation never on a feature path** — two tests: a static check
  that `build_panel` does not name `load_centered`, and a dynamic one that
  monkeypatches `load_centered` to raise and then rebuilds the entire panel and
  the live-quarter treatments.
- **causal fills reproducible from prior data only** — recomputes a fill from
  raw history strictly before the gap and asserts equality.

### D20. Two findings that fell out of the panel before any model was fitted

**(a) The denominator choice flips the sign of the signal.** At 2026Q3 day 30:
`dd_rel_d30` (competitor-only denominator) is **+0.513**, while
`dd_rel_wide_d30` (OTel-inclusive) is **−0.340**. Same data, same construction,
opposite conclusion. This retrospectively vindicates deciding the denominator
a priori on economic grounds (D11): had the choice been made on out-of-sample
score, the selection would have been between two features with *opposite
signs*, and whichever won would have been noise fitted to ~10 test points.

**(b) The placebo is not near zero.** `plc_rel` runs +0.14 to +0.22 across
recent quarters — the unrelated-utility basket also shows strong "excess growth"
against the shrinking control basket. The real feature is larger
(`dd_rel` +0.42 to +0.51), but the placebo is clearly not measuring nothing.
This is an early warning that part of `dd_rel` may be common ecosystem trend
rather than Datadog adoption. It is **not** conclusive — the question is
whether the placebo predicts *revenue* out of sample, which is Phase 4's job
per D17. Recording it now so the Phase 4 result cannot be framed after the fact.

### D21. The relative feature is far more robust to the outage treatment
Live-quarter spread across the three treatments (causal / dropped-rescaled /
raw-with-zeros): the absolute feature `dd_abs` moves 0.0623 log points, the
relative feature `dd_rel` moves **0.0048** — roughly an order of magnitude less.
An API outage suppresses the Datadog and control baskets together, so the
difference cancels it. This is a second, independent argument for the relative
construction, separate from the ecosystem-trend argument in D11.

---

## Pre-Phase-3 checks (2026-08-14)

### D22. Basket composition drift — material, and differencing does NOT fix it
Composition drift is the mirror image of the outage problem (D16): a package
*entering existence* adds a permanent artificial jump to a "sum of packages
that exist today" basket, where an outage subtracted a temporary one.

Presence is defined by **existence** (first date with a 28-day mean above
1,000/day), not by crossing a volume threshold. A package that existed
throughout and merely grew is signal; a package that did not exist is drift.
A first pass used a 10,000/day floor and wrongly emptied the Datadog basket —
it was conflating "hadn't grown yet" with "didn't exist".

The sample's first modellable target quarter is 2020Q1, so a YoY feature needs
history from 2019-01-01. Applying that rule identically to all three baskets:

| basket | kept (constant composition) | dropped |
|---|---|---|
| Datadog | `dd-trace`, `datadog-metrics` | `@datadog/browser-rum` (2019-12), `@datadog/browser-logs` (2019-12), `@datadog/datadog-ci` (2020-03) |
| control | `newrelic`, `elastic-apm-node` | none |
| placebo | `lodash`, `chalk`, `axios`, `react` | none |

The rule binds only on the Datadog basket, because only Datadog launched
packages mid-sample. That asymmetry is in the data, not in the treatment.

**Magnitude.** `basket_all` minus `basket_common`, quarterly YoY log growth:
mean |difference| **0.1215 log points**, max **0.3079** (2022Q1), correlation
0.984. The distortion is concentrated in 2021Q4–2022Q3 (+0.24 to +0.31),
exactly when the three newer packages were ramping, and is still +0.13 in
2026Q2. On a feature whose sample mean is ~0.52, a 0.12 mean distortion is
material. **`basket_common` becomes primary; `basket_all` moves to the
appendix** as `dd_abs_all_*` / `dd_rel_all_*`.

**Correction to the expected mitigation.** The hope was that differencing would
absorb part of this, as it did for outages (D21). It does not: |all − common|
is **0.1215 for all three of** `dd_abs`, `dd_rel` and `dd_rel_plc`, identically.
Differencing cancels a distortion only when it is *common across baskets*. An
outage hits every basket at once, so it cancels. Composition drift here hits
only the numerator, so it passes through the difference untouched. The two
problems look alike and behave oppositely under the same fix.

**Effect on the headline number.** Live 2026Q3 `dd_abs` falls from 0.7493
(constant composition) versus 0.8629 (basket_all) at day 44 — and note the log
scale: 0.7493 is **+112% YoY**, not +86%. The gap against ~36% revenue growth
is therefore wider than a linear reading of the log value suggests, and
composition drift explains only part of it.

**Considered and deferred:** a chain-linked index (per-package YoY aggregated
with prior-year volume weights), which would keep all five packages without
level jumps. It is the textbook answer, but it adds a weighting scheme that
would itself need defending, and the two-package constant basket still covers
~1.70m downloads/day. Noted as the natural extension if this productises.

### D23. OpenTelemetry is in dd-trace's dependency *closure*, not merely its manifest
Direct-dependency evidence was recorded in D11. The transitive check requested
is stronger and is now done — resolving the full dependency closure from the
npm registry:

| dd-trace version | closure size | OpenTelemetry packages in closure |
|---|---|---|
| **v5.60.0** (the line carrying **82.6%** of current installs) | 49 packages | `@opentelemetry/api` (depth 1), `@opentelemetry/core` (depth 1), `@opentelemetry/semantic-conventions` (depth 2) |
| v6 latest | 7 packages | **none** |

This is the sentence for Methodology, and it is a fact rather than an argument:
*for the dd-trace version representing 82.6% of installs, `@opentelemetry/api`
is inside the dependency closure, so putting OpenTelemetry in the denominator
puts the numerator's own dependency traffic in the denominator.*
"OTel is a complement" is an economic argument and can be contested. This
cannot. It is the answer to "how do you know your prior was right", which the
sign flip in D20(a) guarantees will be asked.

### D24. Three candidate features, ranked a priori, BEFORE any Phase 4 result exists
`dd_rel` decomposes **exactly**:

    dd_rel  =  dd_rel_plc  +  plc_rel
    (verified numerically, identity holds to floating point)

Sample means, full-quarter, 2021Q1–2026Q2:

| term | mean (log points) | reading |
|---|---|---|
| `dd_abs` | 0.5216 | Datadog basket growth, no drift adjustment |
| `dd_rel` | 0.3851 | Datadog minus shrinking competitors |
| `dd_rel_plc` | 0.2052 | Datadog minus the unrelated ecosystem |
| `plc_rel` | 0.1799 | **pure mechanical term: ecosystem minus shrinking competitors** |

**47% of `dd_rel`'s mean is the `plc_rel` term** — that is, nearly half of the
apparent Datadog-over-competitor outperformance is the competitor basket
shrinking relative to the general ecosystem, with no Datadog content at all.
The placebo did not merely flag this qualitatively; the decomposition measures
it exactly.

**A priori ranking, fixed now:**

1. **`dd_rel_plc`** — Datadog minus placebo. The placebo basket is large
   (~130m downloads/day), stable, and economically unrelated to Datadog, which
   makes it the cleanest available proxy for ecosystem-wide drift. Removes the
   `plc_rel` mechanical term by construction.
2. **`dd_rel`** — Datadog minus competitors. Retains a defensible
   share-of-substitutes reading, but its denominator is small, shrinking, and
   therefore mechanically inflates the feature.
3. **`dd_abs`** — no drift adjustment at all, and 2026 ecosystem inflation is
   enormous (controls +102%/+184% YoY). Kept because it depends on no benchmark
   choice.

**The headline model uses rank 1 regardless of out-of-sample outcome.** Ranks 2
and 3 are reported alongside as pre-registered alternatives, with their metrics
shown. Selecting among three candidates on ~10 out-of-sample points is the
exact trap identified in D11 and D20(a); the ranking is committed here so that
it cannot be re-derived after the results are visible.

Each candidate carries its own negative control through the identical pipeline:
`dd_rel_plc` → `ctrl_rel_plc`, `dd_rel` → `plc_rel`, `dd_abs` → `plc_abs`.
