# Alternative Data Nowcasting — Datadog (DDOG)
### 8 slides · 15 minutes · speaker notes below each

---

## Slide 1 — The call

# $1,188.5m
### Q3 2026 revenue · 95% band $1,173.8m – $1,203.2m · YoY +34.2%

| | |
|---|---|
| Guidance midpoint | $1,140m *(verified, 8-K 0001628280-26-053829)* |
| Mean beat, out-of-sample-selected window | +4.25% *(sd 0.66pp)* |
| Quarters below the midpoint, ever | **0 of 27** |

**It is not built from alternative data. The next four slides are how I know.**

> **Notes.** Lead with the number. Say the guidance range out loud —
> "$1.135 to $1.145 billion" — I read it in the filing myself. Flag the
> punchline early so the negative result reads as method, not failure.

---

## Slide 2 — How it's built, and why the baseline is honest

**Rule:** guidance midpoint × (1 + mean beat), window length chosen by **nested walk-forward inside the training set only**. MAPE **4.10%**, hit rate **76.9%**.

An earlier version fixed the window at 8 quarters *after* seeing the sample — data snooping on the baseline while the signals faced walk-forward discipline. Removing it **improved** the baseline (RMSE 0.0229 → 0.0200), raising the bar for the signals. For the live quarter the fair rule picks 8 quarters on its own, so the number is unchanged.

Walk-forward residuals: pre-2025 **−1.96pp** (1/7 positive) → 2025 onward **+0.53pp** (5/6). **2026Q2, the largest acceleration in the sample: +0.18pp.**

A revenue-history model must *infer* a regime break. A guidance-anchored rule *inherits* it.

> **Notes.** This answers both "what about the 2026 structural break" and
> "isn't your baseline cheating". The second one matters — I found it myself
> only after a reviewer pushed, and fixing it made my own case harder.

---

## Slide 3 — The test design applied to every signal

**Signals:** npm instrumentation downloads (3 constructions × 4 windows) · hyperscaler cloud segment growth

1. **As-of vintage panel** — features stored as (quarter, value, `available_from`); disclosure dated by the earnings 8-K, not the 10-Q. 13 unit tests, one of which poisons the look-ahead-contaminated loader and rebuilds the whole panel.
2. **Matched negative control for every candidate**, including a placebo basket (`lodash`, `chalk`, `axios`, `react`) with no economic link to Datadog.
3. **Seven baselines**, including ARIMA(1,1,0) and the un-snoopable guidance rule.
4. **Guidance-orthogonalised variant** — features residualised against guidance-implied growth, because the tradable question is the *surprise*, not the level.
5. **Four target metrics** from the brief — revenue growth, beat vs guidance, $100k+ customer growth, billings.
6. **Permutation null, Diebold–Mariano (HLN), 10,000-draw bootstrap, and a power analysis.**

> **Notes.** Spend real time here; this is the deliverable. The a priori feature
> ranking was written into LOG.md D24 before Phase 4 ran — and my top-ranked
> feature lost. That's the system working, not a failure of the system.

---

## Slide 4 — The result, and what the apparent signal actually was

### 0 of 24 cells beat the strongest baseline. 0 again when orthogonalised against guidance.

**The chain, in three facts:**

- vs **AR(1)**, 15 of 24 cells beat 0.9; permutation null gives 0.58 → **p = 0.002**. The features *do* carry information AR(1) lacks.
- A **bare time index** through the identical pipeline also beats AR(1) (0.896). Zero Datadog content.
- vs the **strongest** baseline, that null gives 0.01 cells and the observed count is **0**.

**The information was drift. A correctly specified naive model already has it.**

Corroborating: placebo packages correlate **0.72–0.76 with revenue at every lag −2 to +2** — flat. Performance *degrades* as the window lengthens (0.734 → 0.975); a real signal sharpens.

**The same trap in unstructured text.** I also tested management tone in the earnings press release, with a placebo *inside the same document* — the forward-looking-statements disclaimer written by counsel:

| | corr with next beat | best cell |
|---|---|---|
| management's own words | +0.211 | 1.551 |
| **the lawyer's boilerplate** | **−0.808** | **0.968** |

The disclaimer wins, and against AR(1) it is "significant" (CI [0.533, 0.835], DM p=0.088). Boilerplate drifts as counsel updates the template, so it proxies time.

**What this does and does not prove.** At n=13 the test detects a 5% edge only **6%** of the time, a 10% edge **15%**. So "0 of 24" *bounds* the effect; it does not show it is zero. But the observed cells sit at **1.05–2.65** — that part is measurement, not low power.

> **Notes.** The p=0.002 is not a contradiction, it's the pivot. Say plainly:
> "beating AR(1) sounds like a result until you notice a clock beats AR(1)."
> The boilerplate result is the one to tell if asked about adding LLM-parsed
> research: text features are *more* exposed to spurious trend-fitting, not less.

---

## Slide 5 — The scope of that claim, stated precisely

| Channel | Carries | Cumulative | History |
|---|---|---|---|
| npm basket *(what I could test)* | Node.js APM SDK | 1.13bn | daily, 2017+ |
| **Docker Hub `datadog/agent`** | **core Go agent — hosts, containers, logs** | **11.25bn** | **lifetime counter only** |
| APT/YUM, Helm, marketplaces | core Go agent | not published | none |

**~10× the volume sits in a channel with no history.**

> The finding is **not** "alternative data cannot predict Datadog". It is:
> *the freely and historically observable slice is the wrong slice, and the right slice is not retrospectively observable at all.*

The forward fix is cheap and is the highest-value addition to this pipeline: snapshot the Docker Hub counter daily and you have the correct series **from that day on**. You just cannot recover the 27 quarters already gone.

> **Notes.** Own this. I built the analysis on the channel that was easy to
> observe rather than the one that mattered, and one API call would have caught
> it on day one. That is now the first item in the productisation section.

---

## Slide 6 — The finding that generalises

# Downloads per $1m of revenue: 21,818 → 97,228
### +346% · Spearman ρ = +0.927 · p < 0.0001 · near-monotonic over 28 quarters

**Tested against the standard SaaS explanations, not asserted.** Normalising by disclosed $100k+ ARR customers:

| | first 4 → last 4 |
|---|---|
| revenue per large customer | **+67%** |
| downloads per large customer | **+644%** |

Cross-sell and tiering are **real** — but downloads per customer grew ~10× faster, so monetisation explains a minority. Private-registry mirroring pushes the *opposite* way. CI/CD re-pulls fail too: weekday/weekend ratio 6.39 → 5.61, p=0.77.

**Counts vs dollars:** downloads are an unweighted count, so a count target should fit better — and it does. Best cell against **customer growth 1.049** vs **revenue growth 1.137**. Directionally right, still a loss.

> **Notes.** This is the original-research moment. Pause here. It's a measured,
> generalisable statement about a class of alternative data, not a post-mortem.

---

## Slide 7 — The right role: divergence monitor. Live dashboard.

Headline from the baseline; signals monitor when the baseline breaks. Today's reading *is* the thesis:

| Signal (day 30) | z | State |
|---|---|---|
| Datadog **absolute** | **+2.36** | diverging |
| Datadog vs ecosystem | +0.38 | in line |
| **PLACEBO** vs competitors | +0.93 | in line |

**The ecosystem is running hot, not Datadog.** An absolute-download dashboard would be flashing green right now.

Also on the page: observability table · QTD pace vs prior quarters at the same day · outage-treatment spread (9.1% of this quarter imputed) · risk flags · **and the 0-of-24 grid and the power table, on the face of the dashboard**.

> **Notes.** Show it live. Diagnostics are visible rather than hidden because an
> analyst has to know how much to trust the headline. Thresholds are conventional
> 1σ/2σ, deliberately not fitted.

---

## Slide 8 — Templating, and what this means for a research platform

**Repointing at SNOW or MDB:** CIK + revenue tag · signal basket with its control and placebo baskets · guidance extractor re-pointed. Everything else is ticker-agnostic. **The conclusion is what doesn't transfer.**

| Component | Why, from this project |
|---|---|
| **Observability triage first** | The biggest error here was analysing the easy channel, not the right one. One API call flags "high relevance, zero history" before any modelling. |
| **Matched control as mandatory metadata** | The control turned a 0.79 correlation into a rejected hypothesis — and in text, a legal disclaimer "predicted" earnings surprises at r=−0.81. |
| **As-of vintage as infrastructure** | Asked for "Q2 revenue", an agent fetches *today's* value. Worth 18 days on Q4 here. Test belongs in CI. |
| **Evaluator loop that reports power** | Every negative result should ship with its minimum detectable effect, so "no edge found" is never read as "no edge exists". |

**The deliverable isn't a signal — it's a method that can tell you when you don't have one.**

> **Notes.** Land here, then stop. Don't pitch a roadmap — the pipeline is the
> argument. If they want to go further into productisation, that is what the
> Q&A is for, and the prep notes cover it in depth.
