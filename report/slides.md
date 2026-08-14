# Alternative Data Nowcasting — Datadog (DDOG)
### 8 slides · 15 minutes · speaker notes below each

---

## Slide 1 — The call

# $1,188.5m
### Q3 2026 revenue · 95% band $1,173.8m – $1,203.2m · YoY +34.2%

| | |
|---|---|
| Guidance midpoint | $1,140m *(verified, 8-K 0001628280-26-053829)* |
| Trailing 8-quarter mean beat | +4.25% *(sd 0.66pp)* |
| Quarters below the midpoint, ever | **0 of 27** |

**It is not built from alternative data. I'll show you why in four slides.**

> **Notes.** Lead with the number. Say the guidance range out loud —
> "$1.135 to $1.145 billion" — I read it in the filing myself. Flag the
> punchline early so the negative result lands as method, not as failure.
> Do not apologise for it.

---

## Slide 2 — How it's built, and why guidance anchoring wins

**Rule:** guidance midpoint × (1 + trailing 8-quarter mean beat). MAPE **5.48%**, hit rate **69.2%**.

Walk-forward residuals of this rule:

| period | n | mean residual | positive |
|---|---|---|---|
| pre-2025 | 7 | −1.96pp | 1/7 |
| 2025 onward | 6 | +0.53pp | 5/6 |

**2026Q2 — the largest acceleration in the sample, 24.6% → 35.6% YoY — residual +0.18pp.**

A revenue-history model must *infer* a regime break. A guidance-anchored rule *inherits* it from management.

> **Notes.** This is the answer to "what about the structural break in 2026".
> The brief predicted a model would systematically under-predict 2026; the
> residuals run the other way, and the reason is that guidance already absorbs
> the break. Beat distribution is stationary over the last 16 quarters
> (ADF 0.007 / KPSS 0.100) — that's what makes ±$15m credible.

---

## Slide 3 — So what about the alternative data? Here is the test design

**Signals tested:** npm instrumentation downloads (4 constructions) · hyperscaler cloud segment growth

**The design, applied identically to every one:**

1. **As-of vintage panel** — features stored as (quarter, value, `available_from`); disclosure dated by the earnings 8-K, not the 10-Q. 13 unit tests, including one that poisons the look-ahead-contaminated data loader and rebuilds the whole panel.
2. **Matched negative control for every candidate** — including a placebo basket of `lodash`, `chalk`, `axios`, `react`: packages with no economic connection to Datadog.
3. **Six baselines** — AR(1), AR(1)+trend, random walk, ARIMA(1,1,0), guidance+expanding beat, guidance+trailing beat.
4. **Full 24-cell grid** (3 features × 4 windows × 2 targets), with the post hoc window choice priced by a **permutation null**.
5. **Diebold–Mariano (HLN)** + 10,000-draw bootstrap CI on every error ratio.

> **Notes.** Spend real time here — this slide is the actual deliverable.
> Emphasise that the control and the baseline set were fixed *before* results.
> The a priori feature ranking was written into LOG.md D24 before Phase 4 ran,
> and my top-ranked feature lost. That's the system working.

---

## Slide 4 — The result, and what the apparent signal actually was

### 0 of 24 cells beat the strongest baseline

| Target | `dd_abs` | `dd_rel` | `dd_rel_plc` |
|---|---|---|---|
| `rev_yoy` vs ARIMA(1,1,0) | 1.032 – 1.372 | 1.911 – 2.409 | 1.470 – 1.576 |
| `beat_vs_guide` vs random walk | 1.075 – 1.108 | 1.254 – 1.347 | 1.355 – 1.386 |

**The chain that explains it — three facts:**

- vs **AR(1)**, 15 of 24 cells beat 0.9; permutation null gives 0.58 → **p = 0.002**. The features *do* carry information AR(1) lacks.
- A **bare time index** through the identical pipeline also beats AR(1) (0.896). Zero Datadog content.
- vs the **strongest** baseline, the permutation null gives 0.01 cells and the observed count is **0**.

**The information was drift. A correctly specified naive model already has it.**

Corroborating: placebo packages correlate **0.72–0.76 with revenue at every lag −2 to +2** — flat. And performance *degrades* as the window lengthens (d30 0.734 → full 0.975); a real signal sharpens.

> **Notes.** If one slide gets remembered for method, it's this one. The
> permutation p=0.002 is not a contradiction — it's the pivot. Say plainly:
> "beating AR(1) sounds like a result until you notice a clock beats AR(1)."

---

## Slide 5 — The finding that generalises

# Downloads per $1m of revenue: 21,818 → 97,228
### +346% · Spearman ρ = +0.927 · p < 0.0001 · near-monotonic over 28 quarters

**The proxy decayed ~4.5× over the sample.** Downloads and billable usage have come apart.

- The obvious explanation — CI/CD re-pulls — **is not supported**: weekday/weekend ratio 6.39 → 5.61, slope p = 0.77, flat to *falling*.
- A second test on release-window concentration was **underpowered by construction** and is reported as such, not as a null.
- Untested candidates, named not implied: mirror traffic, container rebuilds, AI coding agents, and the structural one — downloads are unweighted, revenue is dollar-weighted.

**This is why the models fail, and it applies to anyone doing download-based SaaS nowcasting.**

> **Notes.** This is the original-research moment. It's not "my model didn't
> work" — it's a measured, generalisable statement about a whole class of
> alternative data. Pause here.

---

## Slide 6 — The right role for the signals: divergence monitor

**Live dashboard walkthrough.** Headline from the baseline; signals monitor when the baseline breaks.

Today's reading is a working example of the whole thesis:

| Signal (day 30) | z | State |
|---|---|---|
| Datadog **absolute** | **+2.36** | diverging |
| Datadog vs ecosystem | +0.38 | in line |
| **PLACEBO** vs competitors | +0.93 | in line |

**The ecosystem is running hot, not Datadog.** An absolute-download dashboard would be flashing green right now.

Also on the page: QTD pace vs prior quarters at the same day · outage-treatment spread (9.1% of this quarter's observations imputed) · risk flags · **and the 0-of-24 grid, on the face of the dashboard**.

> **Notes.** Show the live page. The reason model diagnostics are visible
> rather than hidden: an analyst has to know how much to trust the headline.
> Thresholds are conventional 1σ/2σ, deliberately not fitted — fitting a
> threshold on 8 points is the error we just spent four slides rejecting.

---

## Slide 7 — Templating: what it takes to point this at SNOW or MDB

**Three changes:**
1. CIK + XBRL revenue tag *(the SEC fetcher is already generic)*
2. Signal basket + its substitute-control basket + an unrelated placebo basket
3. Guidance extractor re-pointed at that issuer's outlook wording

**Unchanged:** as-of vintage layer · outage detection · constant-composition rule · baseline set · walk-forward · permutation null · placebo path · DM/bootstrap.

**What does not transfer is the conclusion.** For an issuer that guides less reliably, the same pipeline could promote a different input — which is the entire point of running the baselines and the placebo *before* choosing.

> **Notes.** Keep this short. The credible version of "it's reusable" is
> naming the three things that change, not claiming everything is generic.

---

## Slide 8 — What this means for a research-agent product

**The headline result is the product insight:** the best nowcast used no alternative data — so the value isn't finding more signals, it's the discipline that stops trend being mistaken for signal.

| Component | Why, from this project |
|---|---|
| **Signal registry with mandatory matched control** | The control is what turned a 0.79 correlation into a rejected hypothesis. A registry without controls ships false positives by default. |
| **As-of vintage as infrastructure** | Look-ahead is the characteristic LLM-agent failure: asked for "Q2 revenue" an agent fetches *today's* value, not the decision-date value. Worth up to 18 days on Q4 here. Unit test belongs in CI. |
| **Automated evaluator loop** | Baselines, placebo, permutation null, DM+bootstrap are mechanical. Highest-value single piece is the placebo path — it converted "we found a signal" into "we found a trend" for one extra run. |

**This two-week workflow is the spec for that product.**

> **Notes.** Land on: the deliverable isn't a signal, it's a method that can
> tell you when you don't have one. That is harder to fake than a backtest,
> and it's what a research platform has to get right to be trusted.
