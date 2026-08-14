# Alternative Data Nowcasting — Datadog (NASDAQ: DDOG)

**Q3 2026 revenue call, the evidence behind it, and what the alternative data does and does not support**

Data through 2026-08-13 · all figures reproducible from committed code · no MNPI

---

## 1. Conclusion

**Q3 2026 revenue: $1,188.5m, 95% band $1,173.8m – $1,203.2m (±$14.7m). Implied YoY +34.2%, QoQ +6.0%.**

The call is built from Datadog's own guidance midpoint of $1,140m — verified verbatim against 8-K Exhibit 99.1, accession 0001628280-26-053829, *"Third Quarter 2026 Outlook: Revenue between $1.135 billion and $1.145 billion"* — multiplied by the trailing eight-quarter mean beat of **+4.25%** (sd 0.66pp, no quarter below the midpoint in 27 on record).

**It is not built from alternative data, and that is the report's main finding.** I built four constructions of a download signal and a hyperscaler signal, ran all of them through an as-of vintage panel, an expanding walk-forward, a six-model baseline set, matched negative controls and a permutation null. **Zero of 24 candidate cells beat the strongest naive baseline.** The signals do carry information that AR(1) lacks (permutation p=0.002) — but that information is *drift*, which a correctly specified naive model already supplies for free. Presenting a signal-weighted revenue estimate would show a relationship my own validation rejected.

Three things the call rests on:

1. **Guidance anchoring absorbs the regime change.** Datadog's growth accelerated from 24.6% (2025Q1) to 35.6% (2026Q2). A revenue-history model must infer that break; a guidance-anchored rule inherits it from management. The rule's walk-forward residual in 2026Q2 — the largest acceleration in the sample — was **+0.18pp**.
2. **The beat distribution is stationary over the recent sample** (ADF p=0.007, KPSS p=0.100 on the last 16 quarters), with sd of just 0.66pp over the last eight. That stability is what makes the ±$15m band credible, and simultaneously why alternative data has so little room to add value.
3. **The alternative data now runs as a divergence monitor, not an estimator** — it flags when this quarter stops looking like the last eight, which is exactly when a trailing-mean rule breaks.

---

## 2. Part 1 — Data selection and rationale

| Source | What it measures / origin | Economic logic and supporting evidence | Frequency · latency · history · coverage | Cost | Key limitations → mitigations | Status |
|---|---|---|---|---|---|---|
| **1. npm instrumentation downloads** — `dd-trace`, `datadog-metrics` (constant-composition basket); controls `newrelic`, `elastic-apm-node`; placebo `lodash`, `chalk`, `axios`, `react` | Daily package downloads from the public npm registry API | Datadog bills on hosts, custom metrics, ingested spans and logs (10-K, "usage-based" revenue). Customers emit that telemetry only by installing instrumentation, so downloads proxy the *billable unit* rather than sentiment. Empirically: contemporaneous corr with `rev_yoy` = 0.79 (n=27) | Daily · 1-day latency (verified) · back to 2015 · Node.js ecosystem only | Free, no auth | CI/CD re-pulls ≠ installs; mirror traffic; version-release spikes; no revenue weighting → YoY log differences not levels; mandatory control and placebo baskets; constant composition; outage detection and backward-only imputation | **Tested** |
| **2. Hyperscaler cloud segment growth** — Microsoft Intelligent Cloud (28/28 quarters), AWS (16/28), Google Cloud (8/28); controls MSFT Productivity & Business Processes, AMZN total net sales | Segment growth rates from Item 2.02 8-K press releases. *Not available in XBRL* — the `companyfacts` endpoint returns consolidated facts only and drops the segment axis | Datadog monitors workloads running on AWS/Azure/GCP and sells through their marketplaces; cloud segment growth is the closest public proxy for the underlying workload pool. **Timing verified rather than assumed**: all three peers reported before Datadog in all 28 quarters (AMZN median lead 7 days, not the two weeks commonly assumed) | Quarterly · reported 5–19 days before DDOG · 28 quarters · three vendors | Free | Recent growth is heavily AI-capex driven and correlates weakly with application-monitoring workloads → matched non-cloud control from the *same filing*; extraction audited for >25pp jumps | **Tested** |
| **3. PyPI downloads** — `ddtrace`, `datadog`, `datadog-api-client` | Daily downloads, `without_mirrors` category, pypistats.org | Same billable-unit logic as npm, in the Python ecosystem. Intended as cross-ecosystem confirmation that the npm signal is not a JavaScript-registry artefact | Daily · 1-day latency · **181 days only** · Python ecosystem | Free (long history needs BigQuery, out of scope) | 181 days cannot produce a YoY, so the test was underpowered by construction; it failed to confirm and that null is **not** treated as evidence against the signal | **Cross-check only — underpowered** |
| **4. Hiring / job-postings demand** — count of employer postings requiring "Datadog" as a skill; Datadog's own sales headcount | Job-posting aggregators (Revelio, LinkUp, Coresignal) | Adoption breadth plausibly leads bookings by 2–3 quarters, and sales headcount is capacity for future bookings. A widely used practitioner signal for enterprise software | Daily/weekly · days · vendor-dependent (typically 2015+) · US-skewed | **Vendor-provided, paid** | No free source with usable history exists; postings over-weight large employers and are seasonal → would require de-seasonalising and an employer-fixed-effects panel | **Proposed, not tested — vendor-dependent history** |
| **5. Competitive displacement / cost sentiment** — Stack Exchange tag volume; GitHub activity on `DataDog/datadog-agent` vs `grafana/grafana` and OpenTelemetry; volume of cost-complaint discussion | Stack Exchange API, GitHub REST API, both public | Positioned explicitly as a **downside-risk proxy for net revenue retention, not a revenue predictor**. Datadog bill shock is a well-documented churn vector among engineering teams | Daily · days · 2010+ (SO), 2012+ (GitHub) · global, developer-skewed | Free | Sentiment volume tracks community size, not spend; vocal minority bias; no dollar weighting → would need a share-of-tag-volume construction and a matched competitor baseline. **Deliberately not forced into the revenue model** | **Proposed, not tested — risk proxy by design** |

**One finding from Part 1 that changed the analysis.** `dd-trace` v5 — carrying **82.6%** of current installs — declares `@opentelemetry/api` inside its dependency closure (depth 1, alongside `@opentelemetry/core`; v6 drops it). A control basket containing OpenTelemetry would therefore contain traffic generated by the numerator. This is a fact about the dependency graph, not an economic argument, and it is why the denominator excludes OTel.

---

## 3. Part 2 — Methodology and results

### 3.1 As-of construction

Features are stored as **vintages** — one row per (quarter, feature, value, `available_from`) — so requesting a feature set is a filter, not a judgement. 1,666 vintage rows, 50 features. `available_from` is the earnings 8-K date, **not** the 10-Q filing date: the 8-K leads the 10-Q by a median of 1 day but by up to 18 days for Q4. Reporting lag measured, not assumed: median 38 days, 34–47 range, systematically longer for Q4 (44 vs 36–38).

Thirteen unit tests enforce this, including a static check that the feature builder never references the look-ahead-contaminated imputation variant and a dynamic check that poisons that loader and rebuilds the entire panel.

### 3.2 Lead–lag

Both targets are **non-stationary** (`rev_yoy` ADF p=0.063 / KPSS p=0.022; `beat_vs_guide` ADF p=0.079 / KPSS p=0.028). That matters more than it first appears — see §3.4.

Cross-correlation gives the first warning. `dd_abs` correlates 0.86–0.89 with `rev_yoy` and peaks at lag −1, which looks like a leading indicator. But the **placebo basket** — `lodash`, `chalk`, `axios`, `react`, packages with no economic connection to Datadog whatsoever — correlates **0.72, 0.76, 0.73, 0.73, 0.73 across lags −2 to +2**. A flat correlation profile at that level, from packages that cannot possibly contain Datadog information, is the signature of common trend.

The operationally meaningful test is the partial-quarter one: does the first 45 days predict the quarter out of sample? For `dd_abs` on `rev_yoy` the RMSE ratio vs AR(1) runs **0.734 (d30) → 0.860 (d45) → 0.895 (d60) → 0.975 (full)**. Performance *degrades* as observations accumulate. A real signal sharpens with more data; trend-phase fitting does the opposite.

### 3.3 Baselines — run first

| Target | AR(1) | AR(1)+trend | Random walk | ARIMA(1,1,0) | Guidance + expanding beat | Guidance + trailing-8 beat |
|---|---|---|---|---|---|---|
| `rev_yoy` RMSE | 0.0309 | 0.0379 | 0.0263 | **0.0220** | 0.0306 | 0.0229 |
| `rev_yoy` MAPE % | 7.47 | 12.57 | 6.03 | 5.59 | 10.19 | **5.48** |
| `rev_yoy` hit rate | 0.385 | 0.462 | n/a* | 0.615 | 0.615 | **0.692** |
| `beat_vs_guide` RMSE | 0.0183 | 0.0164 | **0.0119** | **0.0119** | 0.0298 | 0.0227 |

\* the random walk predicts no change, so its directional hit rate is undefined rather than zero.

**AR(1) is the worst or near-worst baseline on both targets.** On the assignment's own metrics — MAPE and hit rate — the best `rev_yoy` nowcast is the guidance midpoint plus the trailing eight-quarter mean beat: MAPE 5.48%, hit rate 69.2%, using no alternative data at all. (The 8-quarter window is a *post hoc* choice, made after observing that the expanding mean is contaminated by the 2020–21 regime; it raises the bar for the signals rather than lowering it.)

### 3.4 The result

Three candidate features × four windows × two targets = 24 cells, each with a matched negative control. Scored against the **strongest** baseline per target:

| Target | Feature | d30 | d45 | d60 | full |
|---|---|---|---|---|---|
| `rev_yoy` vs ARIMA(1,1,0) | `dd_abs` | 1.032 | 1.210 | 1.259 | 1.372 |
| | `dd_rel` | 1.911 | 1.928 | 2.078 | 2.409 |
| | `dd_rel_plc` | 1.470 | 1.516 | 1.536 | 1.576 |
| `beat_vs_guide` vs random walk | `dd_abs` | 1.105 | 1.108 | 1.075 | 1.108 |
| | `dd_rel` | 1.347 | 1.295 | 1.254 | 1.294 |
| | `dd_rel_plc` | 1.364 | 1.361 | 1.355 | 1.386 |

**0 of 24.** Not one cell, at any horizon, on either target.

**The three-sentence chain that explains it.** Against AR(1), 15 of 24 cells score below 0.9, and a permutation null (1,000 draws, feature values shuffled across quarters) produces only 0.58 such cells on average — p=0.002, so the features genuinely carry information AR(1) does not have. But a **trend-only feature**, a bare time index pushed through the identical pipeline, also beats AR(1) on `beat_vs_guide` (ratio 0.896) while containing zero Datadog information. Against the strongest baseline the same permutation null produces 0.01 cells and the observed count is 0 — the information the features carry is drift, and a correctly specified naive model already has it.

Significance testing confirms this. Of 24 rows tested with Diebold–Mariano (HLN small-sample correction) and a 10,000-draw bootstrap, exactly one candidate cell has a CI excluding 1.0: `dd_abs_d45` on `beat_vs_guide`, ratio 0.718, CI [0.604, 0.834], DM p=0.070 — **against AR(1) only**. The same cell against a random walk is ratio 1.108, CI [0.534, 1.784], DM p=0.721.

**Signal 2 fails more decisively.** Microsoft Intelligent Cloud growth scores 2.912 on `rev_yoy` vs ARIMA(1,1,0), CI [1.671, 5.970], DM p=0.025 — significantly *worse* than the baseline. It does achieve an 0.846 directional hit rate while carrying ~3× the baseline error: right direction, badly wrong magnitude, which is why a hit rate alone is a poor metric.

---

## 4. Why it fails: the download-to-revenue coupling has decayed

This is the report's most transferable finding, and it applies to anyone attempting download-based SaaS nowcasting, not just to Datadog.

Part 1's economic argument is that instrumentation downloads proxy the billable unit. If that holds, downloads per dollar of revenue should be roughly stable. It is not:

> **Downloads per $m of revenue: 21,818 → 97,228 over the sample. +346%. Spearman ρ = +0.927, p < 0.0001, near-monotonic across 28 quarters.**

The proxy has degraded by roughly a factor of 4.5. A model mapping download growth to revenue growth assumes a stable coupling; that coupling demonstrably does not hold here. The walk-forward failure is not a small-sample accident — it is what a decaying proxy relationship should produce.

**The obvious explanation is not supported.** If a rising share of downloads were CI/CD re-pulls rather than deployments, weekday concentration should rise. It does not: the weekday/weekend ratio ran 6.39 → 5.61, slope −0.006/quarter, p=0.77 — flat to slightly *falling*. A second test on release-window concentration was **underpowered by construction** (dd-trace publishes so frequently that a 7-day window covers most of the calendar) and is reported as such rather than as a null.

I cannot attribute the decay to a specific mechanism with public data. Candidates that remain untested and are named rather than implied: mirror and proxy traffic growth, container image rebuilds, AI coding agents generating repeated installs, and the structural point that downloads are unweighted while revenue is dollar-weighted — one enterprise and one hobbyist count the same.

---

## 5. Limitations and what the data does not support

**The interval is conditional.** ±$14.7m reflects *only* the historical variance of the beat. Guidance extraction error is zero (every figure re-fetched from EDGAR and matched to its verbatim outlook sentence). Regime risk in the beat distribution is second-order for this call: the flat trailing-mean gives $1,188m and a trend-extrapolated alternative gives $1,195m, a $7m spread inside the band. What the interval does **not** cover: a change in guidance philosophy, a customer-concentration event, or M&A. Formally, the band is *conditional on the beat distribution remaining stationary* — supported over the last 16 quarters, mildly strained over the last 8 (Spearman ρ=+0.69, p=0.058).

**Sample size dominates everything.** 27 usable quarters, 13–14 out-of-sample predictions. Every hit rate in this report is indistinguishable from chance at that n (two-sided binomial p ≥ 0.18 in all cases). Granger tests were run and are reported as descriptive only; at n≈24 they cannot support a causal claim, and the negative controls Granger-"cause" revenue about as readily as the signals do. This sample size is also why the models are OLS with at most two predictors — gradient boosting or a sequence model would fit the trend beautifully and validate nothing.

**A result that flips on 0.34% of the data is not a result.** The npm API returns registry-wide zeros on 12 of 3,512 days. Removing them moves the cross-registry correlation from *below* its placebo (0.932 vs 0.951) to *above* it (0.972 vs 0.961). That fragility is itself the evidence that the 26-week correlation test cannot support a conclusion either way — it is reported as grounds for the inconclusive verdict, not as a repair that rescued the signal.

**Known biases carried, not solved.** Downloads ≠ installs; composition drift required dropping three Datadog packages that did not exist at the start of the sample (their inclusion distorts YoY growth by up to 0.31 log points, and differencing does *not* remove it because only the numerator basket changed); PyPI history is 181 days; Signals 3 and 4 are described but untested.

---

## 6. Productisation — what this becomes as an agent workflow

The headline result is itself the product insight. **The best available nowcast of Datadog's revenue is the company's own guidance plus its recent beat history, and four alternative-data constructions could not improve on it.** For a research-agent platform the value is therefore not in finding more signals, but in the discipline that stops an analyst — or an LLM — from mistaking trend for signal. Three components, each built by hand here:

**A signal registry with metadata.** Each signal carries frequency, latency, history, coverage, cost, and — critically — its *matched negative control* and its *composition rule*. The control is not optional metadata; it is what turned a 0.79 correlation into a rejected hypothesis. A registry that stores a signal without its control ships false positives by default.

**As-of vintage management as a first-class service.** Look-ahead bias is the characteristic failure mode of LLM research agents: an agent asked for "Datadog's Q2 revenue" fetches the *current* value of a source, not the value available at the decision date. Here that distinction was worth up to 18 days on Q4 disclosures and forced a split between backward-only and centred imputation. The vintage layer belongs in infrastructure, with its unit test — *no feature may carry a source timestamp later than the as-of date* — running in CI rather than in an analyst's head.

**An automated evaluator loop.** The pipeline that decided this project's conclusion is entirely mechanical: a complete baseline set including drift-adjusted naive models, a matched placebo through the identical path, a grid whose post hoc degrees of freedom are priced by a permutation null, and DM tests with bootstrap intervals. It should run on every candidate signal and return a verdict, instead of relying on an analyst remembering to ask whether AR(1) was a fair opponent. The highest-value single component is the placebo path — it converted "we found a signal" into "we found a trend" for the cost of one extra run.

**Reusability.** Repointing at SNOW or MDB takes three changes — CIK and revenue tag, a signal basket with its control and placebo baskets, and the guidance extractor re-pointed at that issuer's wording. Everything else is ticker-agnostic. The conclusion is what does not transfer: for an issuer that guides less reliably the same pipeline could promote a different input, which is the point of running the baselines first.

---

*Sources: SEC EDGAR XBRL company facts and Item 2.02 8-K exhibits (Datadog CIK 0001561550; Amazon 0001018724; Microsoft 0000789019; Alphabet 0001652044); npm registry downloads API; pypistats.org. Every figure traces to a cached raw response or a cited accession number. Guidance figures re-fetched from EDGAR and matched to verbatim outlook sentences. Decision record: `LOG.md`, entries D1–D35.*
