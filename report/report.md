# Alternative Data Nowcasting — Datadog (NASDAQ: DDOG)

**Q3 2026 revenue call, the evidence behind it, and what the observable data does and does not support**

Data through 2026-08-13 · all figures reproducible from committed code · no MNPI

---

## 1. Conclusion

**Q3 2026 revenue: $1,188.5m, 95% band $1,173.8m – $1,203.2m (±$14.7m). Implied YoY +34.2%, QoQ +6.0%.**

Built from Datadog's guidance midpoint of $1,140m — verified verbatim against 8-K Exhibit 99.1, accession 0001628280-26-053829, *"Third Quarter 2026 Outlook: Revenue between $1.135 billion and $1.145 billion"* — times the mean beat over a trailing window **whose length is selected by nested walk-forward on training data only**. That rule delivers MAPE 4.10% and a 76.9% hit rate out of sample, using no alternative data.

**The alternative data did not survive validation, and the scope of that claim matters.** Across two signals, three constructions, four horizons and four target metrics — with matched controls, a permutation null and Diebold–Mariano tests throughout — **no cell beat the strongest naive baseline**. But the honest statement is narrower than "alternative data cannot predict Datadog":

> The **freely and historically observable** slice of Datadog's telemetry footprint is the wrong slice, and the right slice is **not retrospectively observable at all**.

Datadog's core billable unit is the Go agent, shipped via Docker Hub, APT/YUM, Helm and cloud marketplaces. `datadog/agent` has 11.25bn cumulative Docker pulls against 1.13bn lifetime npm downloads for the basket this study could measure — **10× the volume, and Docker Hub publishes only a lifetime counter with no history**. What was testable is one product line's SDK; what matters cannot be backfilled.

Three things the call rests on:

1. **Guidance anchoring absorbs the regime change.** Growth accelerated from 24.6% (2025Q1) to 35.6% (2026Q2). A revenue-history model must infer that break; a guidance-anchored rule inherits it. Its walk-forward residual in 2026Q2, the largest acceleration in the sample, was **+0.18pp**.
2. **The beat distribution is stationary over the recent sample** (ADF p=0.007, KPSS p=0.100 on the last 16 quarters), sd 0.66pp over the last eight.
3. **The signals run as a divergence monitor, not an estimator** — flagging when the quarter stops resembling the last eight, which is when a trailing-mean rule breaks.

---

## 2. Part 1 — Data selection and rationale

**What is observable, and what is not** — this determines everything downstream:

| Distribution channel | Carries | Cumulative | History available | Testable here |
|---|---|---|---|---|
| npm `dd-trace`, `datadog-metrics` | Node.js APM SDK | 1.13bn | daily, 2017+ | **yes** |
| **Docker Hub `datadog/agent`** | **core Go agent — host, container, log collection** | **11.25bn** | **lifetime counter only** | **no** |
| APT / YUM, Helm, cloud marketplaces | core Go agent | not published | none | no |

| Source | What it measures / origin | Economic logic and evidence | Freq · latency · history · coverage | Cost | Limitations → mitigations | Status |
|---|---|---|---|---|---|---|
| **1. npm instrumentation downloads** — `dd-trace`, `datadog-metrics`; controls `newrelic`, `elastic-apm-node`; placebo `lodash`, `chalk`, `axios`, `react` | Daily downloads, npm registry API | Datadog bills on hosts, metrics, spans and logs; customers emit telemetry by installing instrumentation, so downloads proxy the billable unit. Contemporaneous corr with `rev_yoy` 0.79 (n=27) | Daily · 1-day latency · 2015+ · **Node.js APM only, ~10% of observable install volume** | Free | CI re-pulls ≠ installs; mirrors; no revenue weighting; **one SDK of a multi-product platform** → YoY log differences, mandatory control and placebo baskets, constant composition, outage imputation, count-type targets | **Tested** |
| **2. Hyperscaler cloud segment growth** — MSFT Intelligent Cloud (28/28), AWS (16/28), GCP (8/28); controls MSFT Productivity & Business Processes, AMZN net sales | Item 2.02 8-K press releases; not in XBRL — `companyfacts` drops the segment axis | Datadog monitors workloads on AWS/Azure/GCP. **Timing verified**: all three reported before Datadog in all 28 quarters (AMZN median lead 7 days, not two weeks) | Quarterly · 5–19 days before DDOG · 28 quarters | Free | AI-capex growth correlates weakly with application monitoring → matched non-cloud control from the *same filing* | **Tested** |
| **3. PyPI downloads** — `ddtrace`, `datadog`, `datadog-api-client` | pypistats.org, `without_mirrors` | Same logic in the Python ecosystem; intended as cross-ecosystem confirmation | Daily · 1 day · **181 days** | Free (history needs BigQuery, out of scope) | No YoY computable, so underpowered by construction; failed to confirm, and that null is not used as evidence against the signal | **Cross-check — underpowered** |
| **4. Hiring / job postings** — postings requiring "Datadog"; sales headcount | Revelio, LinkUp, Coresignal | Adoption breadth plausibly leads bookings 2–3 quarters; headcount is future capacity | Daily/weekly · days · vendor-dependent · US-skewed | **Vendor, paid** | No free source with usable history; over-weights large employers → de-seasonalise, employer fixed effects | **Proposed, not tested** |
| **5. Competitive displacement / cost sentiment** — Stack Exchange tags; GitHub vs `grafana/grafana`, OpenTelemetry | Public APIs | **Downside-risk proxy for NRR, not a revenue predictor.** Bill shock is a documented churn vector | Daily · days · 2010+ | Free | Volume tracks community size, not spend → share-of-tag construction, matched competitor baseline. **Not forced into the revenue model** | **Proposed, not tested** |

**A dependency-graph fact that fixed the control basket.** `dd-trace` v5 — **82.6%** of installs — carries `@opentelemetry/api` in its dependency closure at depth 1 (v6 drops it), so a control containing OpenTelemetry would contain numerator-generated traffic. The denominator excludes OTel on a fact, not a judgement.

---

## 3. Part 2 — Methodology and results

### 3.1 As-of construction

Features are stored as **vintages** — (quarter, feature, value, `available_from`) — so requesting a feature set is a filter, not a judgement. 1,666 rows, 50 features. `available_from` is the earnings 8-K date, not the 10-Q filing date (the 8-K leads by a median of 1 day, up to 18 for Q4). Reporting lag measured, not assumed: median 38 days, range 34–47. Thirteen unit tests enforce this, including a static check that the feature builder never references the look-ahead-contaminated imputation variant, and a dynamic one that replaces that loader with a raising stub and rebuilds the panel.

### 3.2 Lead–lag

Both revenue targets are **non-stationary** (`rev_yoy` ADF p=0.063 / KPSS p=0.022). `dd_abs` correlates 0.86–0.89 with `rev_yoy`, peaking at lag −1 — apparently a leading indicator. But the **placebo basket** correlates **0.72–0.76 at every lag from −2 to +2**. A flat profile at that level, from packages that cannot contain Datadog information, is the signature of common trend. And partial-quarter performance *degrades* as observations accumulate — 0.734 (d30) → 0.975 (full) against AR(1). A real signal sharpens.

### 3.3 Baselines — including one built to be un-snoopable

An earlier version used a trailing 8-quarter window chosen after seeing the sample. That is data snooping on the baseline while the signals faced walk-forward discipline. Replaced: **`guidance + auto-window beat`** selects the window from {4, 6, 8, 12, expanding} by nested walk-forward *inside the training set only*.

| Target | AR(1) | AR(1)+trend | Random walk | ARIMA(1,1,0) | Guidance + expanding | **Guidance + auto-window** |
|---|---|---|---|---|---|---|
| `rev_yoy` RMSE | 0.0309 | 0.0379 | 0.0263 | 0.0220 | 0.0306 | **0.0200** |
| `rev_yoy` MAPE % | 7.47 | 12.57 | 6.03 | 5.59 | 10.19 | **4.10** |
| `rev_yoy` hit | 0.385 | 0.462 | n/a\* | 0.615 | 0.615 | **0.769** |
| `beat_vs_guide` RMSE | 0.0183 | 0.0164 | **0.0119** | **0.0119** | 0.0298 | 0.0174 |

\* the random walk predicts no change, so its hit rate is undefined, not zero.

**Removing the snooping made the baseline stronger** (RMSE 0.0229 → 0.0200; MAPE 5.48% → 4.10%), raising the bar for the signals. For the live quarter the fair rule independently selects the 8-quarter window, so the published call is unchanged — same number, legitimate derivation.

### 3.4 The result

Three features × four windows × two revenue targets = 24 cells, each with a matched control, scored against the strongest baseline — then re-run with each feature **orthogonalised against guidance-implied growth**, because a quantamental desk predicts the surprise around guidance rather than replacing it.

| Feature treatment | Cells beating the strongest baseline | Best cell |
|---|---|---|
| raw | **0 of 24** | 1.075 |
| guidance-orthogonalised | **0 of 24** | 1.323 |

Orthogonalising makes the features *worse*: once what guidance already implies is stripped out, less remains.

All three metrics the brief asks for, on the best cell per target:

| Best candidate cell | RMSE ratio | MAPE | Hit rate | Baseline MAPE | Baseline hit |
|---|---|---|---|---|---|
| `rev_yoy` · `dd_abs_d30` | 1.137 | 7.24% | 0.538 | **4.10%** | **0.769** |
| `beat_vs_guide` · `dd_abs_d60` | 1.075 | 30.8% | 0.571 | **24.7%** | n/a\* |

The signal loses on error *and* direction, not just RMSE.

**The chain that explains it.** Against AR(1), 15 of 24 cells score below 0.9 while a permutation null (1,000 draws, features shuffled across quarters) yields 0.58 — **p = 0.002**, so the features do carry information AR(1) lacks. But a **bare time index** through the identical pipeline also beats AR(1) (0.896) with zero Datadog content, and against the strongest baseline the same null yields 0.01 cells against an observed **0**. The information was drift, which a correctly specified naive model already supplies.

Of 24 significance tests, exactly one cell has a bootstrap CI excluding 1.0: `dd_abs_d45` on `beat_vs_guide`, ratio 0.718, CI [0.604, 0.834], DM p=0.070 — **against AR(1) only**; against a random walk it is 1.108, CI [0.534, 1.784].

**Signal 2 fails harder.** Intelligent Cloud growth scores 2.912 vs ARIMA(1,1,0), CI [1.671, 5.970], DM p=0.025 — significantly *worse*. It hits 0.846 on direction while carrying ~3× the error: right direction, wrong magnitude, and a clean demonstration of why hit rate alone is a poor metric.

### 3.5 The assignment's other target metrics

The Objective names billings/RPO, NRR and $100k+ ARR customer growth. Testing them also tests a hypothesis the download signal implies: **downloads are an unweighted count while revenue is dollar-weighted**, so a count-type target should match better.

| Target | Source | Quarters | n_oos | Strongest baseline | Cells beating it | Best cell |
|---|---|---|---|---|---|---|
| `cust_yoy` ($100k+ ARR customers) | press release | 28 | 11 | ARIMA(1,1,0) | **0 of 12** | **1.049** |
| `billings_yoy` (revenue + Δdeferred) | XBRL | 26 | 7 | AR(1) | 0 of 12 | 1.106 |
| `rpo_yoy` | XBRL | 20 | — | — | not testable | insufficient history |
| NRR | — | — | — | — | **not disclosed numerically in 8-K exhibits** | excluded, not approximated |

**Directionally supported, still insufficient.** Against customer growth the best cell is **1.049** — the closest any signal came to a baseline here, versus 1.137 against revenue growth. Matched controls fail on those cells (1.69–1.83), so the residual edge is attributable. But 1.049 is a loss, at n=11.

### 3.6 One unstructured signal, and the sharpest placebo result in the project

Management tone is the one qualitative signal that is cleanly backfillable — the 8-K press release is free, cached for 28 quarters, and timestamped *at the guidance-issuance moment*. Hypothesis: heavier hedging when guidance is issued means a lower bar, so a larger beat. The design point is the placebo: every release carries a forward-looking-statements disclaimer written by counsel, not management, and tone measured there should predict nothing.

| Measure | corr with subsequent beat | best walk-forward cell |
|---|---|---|
| management body, net tone | +0.211 (p=0.291) | 1.551 |
| **counsel's boilerplate, net tone** | **−0.808 (p<0.001)** | **0.968** |

**The legal disclaimer outperforms management's own words on every comparison**, and against AR(1) yields 0.627, CI [0.533, 0.835], DM p=0.088 — a "significant" result from text written to convey no information. Boilerplate drifts as counsel updates the template, so it proxies time. Same trap, unstructured. The implication inverts the intuition: text features are **more** exposed to spurious trend-fitting than structured ones, so control discipline matters more than extraction quality. *(Compact lexicon, not full Loughran-McDonald; a better one moves the estimates, not the comparison.)*

---

## 4. Why it fails: the observable channel has decoupled from billings

Part 1's logic is that instrumentation downloads proxy the billable unit. If so, downloads per dollar should be roughly stable. They are not:

> **Downloads per $m of revenue: 21,818 → 97,228 over the sample. +346%. Spearman ρ = +0.927, p < 0.0001, near-monotonic across 28 quarters.**

**Tested against the obvious SaaS explanations rather than asserted.** Volume discounts and multi-product cross-sell would raise revenue per customer without raising downloads, and private registries fan one pull out to thousands of hosts. Normalising by the disclosed $100k+ ARR customer count:

| Series | first 4 → last 4 | Spearman ρ |
|---|---|---|
| revenue per $100k+ customer | **+67%** | +0.993 |
| downloads per $100k+ customer | **+644%** | +0.981 |

Cross-sell and tiering are real — revenue per large customer rose 67% — but downloads per large customer rose **roughly ten times faster**. Per-customer monetisation explains a minority of the gap. Private-registry mirroring pushes the *opposite* way and cannot explain a 644% rise either. The decoupling survives the correct normalisation.

**The CI/CD explanation also fails.** If re-pulls were rising, weekday concentration should rise; the weekday/weekend ratio went 6.39 → 5.61, slope p=0.77. A release-window test was **underpowered by construction** (dd-trace publishes so often that a 7-day window covers most of the calendar) and is reported as such, not as a null. Remaining candidates — mirror traffic, container rebuilds, AI coding agents — are named, not implied to be ruled out.

---

## 5. Limitations and what the data does not support

**Power, quantified rather than conceded.** At n=13 a Diebold–Mariano test detects an RMSE ratio of 0.95 only **6%** of the time, 0.90 **15%**, 0.80 **28%** — **a genuine 5–10% edge would have gone undetected roughly 85–90% of the time**. So "0 of 24" *bounds* the effect size rather than showing it is zero. Not a power problem: the observed cells sit at **1.05 to 2.65**, consistent large degradation on the wrong side of parity.

**Scope.** The conclusion applies to the freely observable channel: the core agent's distribution is ~10× larger and exposes no history, so the best-matched proxy was never testable. That is a statement about data availability, not about whether telemetry deployment tracks Datadog's business.

**The interval is conditional.** ±$14.7m reflects only the historical variance of the beat. Guidance extraction error is zero — every figure re-fetched from EDGAR and matched to its verbatim outlook sentence. Regime risk is second-order: flat trailing-mean gives $1,188m, trend-extrapolation $1,195m, a $7m spread inside the band. Not covered: guidance-philosophy change, customer concentration, M&A (Datadog acquired Adaptive ML in the quarter). Formally the band is *conditional on the beat distribution remaining stationary* — supported over 16 quarters, mildly strained over 8 (ρ=+0.69, p=0.058).

**Sample size.** 27 usable quarters, 7–14 out-of-sample points depending on target. Every hit rate here is indistinguishable from chance (binomial p ≥ 0.18). Granger tests are descriptive only. This is also why the models are OLS with at most two predictors. Relatedly, a result that flips on 0.34% of the data is not a result: removing 12 outage days out of 3,512 moves the cross-registry correlation from below its placebo (0.932 vs 0.951) to above it (0.972 vs 0.961), and that fragility is grounds for the inconclusive verdict, not a repair.

---

## 6. Productisation — what this becomes as an agent workflow

**The headline result is the product insight.** The best nowcast used the company's own guidance and no alternative data — so the constraint on research quality is not signal count, it is the ability to distinguish a signal from a trend. Every component below is specified from an incident in this project rather than from first principles, and each is a place where an LLM agent's *default* behaviour is the wrong one:

**Observability triage, before modelling.** The largest error here was analysing the channel that was *easy* to observe rather than the one that *matters*. A registry should record, per candidate, what share of the economic quantity it sees and whether history exists — `datadog/agent` would have been flagged instantly as high-relevance, zero-history. One API call, and it reframes the project on day one.

**Matched controls as mandatory metadata.** The control turned a 0.79 correlation into a rejected hypothesis, and §3.6 shows the stakes rise with text, where a legal disclaimer "predicted" earnings surprises at r=−0.81. A registry storing a signal without its control ships false positives by default.

**As-of vintage as infrastructure.** Look-ahead is the characteristic LLM-agent failure: asked for "Q2 revenue" an agent fetches *today's* value, not the decision-date value. Worth 18 days on Q4 here. The test — *no feature may carry a source timestamp later than the as-of date* — belongs in CI.

**An automated evaluator that reports power.** Baselines, placebo, permutation null and DM with bootstrap intervals are mechanical, and a harness runs all of them where an analyst runs the one they thought of. Every negative result should ship with its **minimum detectable effect**, so "no edge found" is never read as "no edge exists".

**Reusability.** Repointing at SNOW or MDB takes three changes — CIK and revenue tag, a signal basket with its control and placebo, the guidance extractor re-pointed. What does not transfer is the conclusion: for an issuer that guides less reliably the same pipeline could promote a different input, which is the point of running baselines first.

---

*Sources: SEC EDGAR XBRL company facts and Item 2.02 8-K exhibits (DDOG CIK 0001561550; AMZN 0001018724; MSFT 0000789019; GOOGL 0001652044); npm registry downloads API; pypistats.org; Docker Hub public repository API. Every figure traces to a cached raw response or a cited accession number. Decision record: `LOG.md`, D1–D43.*
