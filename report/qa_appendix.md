# Q&A appendix — one answer per decision point

Five minutes is two or three questions. These are the ones a buy-side reviewer
is most likely to reach for, each already resolved during the work. Answer in
two sentences, then stop.

---

### "Your headline uses no alternative data. Isn't that a failed assignment?"

The assignment asked for evidence, and this is what the evidence supports —
it explicitly says a well-validated simple model beats an overfit sophisticated
one, and asks me to be explicit about what the data does and does not support.
I tested two signals across 24 validated cells; none beat a correctly specified
naive baseline, and I can show exactly why. A version that reported a
signal-weighted estimate would be reporting a relationship my own validation
rejected.

### "Why is OpenTelemetry excluded from the control basket?"

Not on judgement — on the dependency graph. `dd-trace` v5, which carries
**82.6%** of current installs, has `@opentelemetry/api` inside its dependency
closure at depth 1 (`@opentelemetry/core` too, and
`@opentelemetry/semantic-conventions` at depth 2); v6 drops it. Putting OTel in
the denominator puts the numerator's own dependency traffic in the denominator.
The OTel-inclusive variant is in the appendix as a labelled sensitivity test.

### "You beat AR(1) on 15 of 24 cells with p=0.002. Why isn't that a signal?"

Because AR(1) is a weak opponent on a non-stationary target — it is the worst
or near-worst of my six baselines on both targets. A bare time index, containing
no Datadog information at all, also beats AR(1) (ratio 0.896). Against the
strongest baseline the permutation null produces 0.01 cells and the observed
count is 0. The features carry drift; a correctly specified naive model already
has it.

### "The 8-quarter trailing window wasn't pre-registered. Isn't that a free parameter?"

Correct, and it's flagged as post hoc in the report. I chose it after observing
that the expanding mean is contaminated by the 2020–21 regime, when beats ran to
12.1% against a recent level near 4.3%. It matters that this choice moves the
bar for the signals **up**, not down — it makes the baseline harder to beat, so
it cannot flatter my conclusion.

### "You cleaned the data and the conclusion flipped. How do I know that's not the tail wagging the dog?"

Take it as evidence *for* the inconclusive verdict, not as a repair. Removing
0.34% of observations (12 registry-wide outage days out of 3,512) moves the
cross-registry correlation from below its placebo to above it — a result that
fragile cannot support a conclusion either way, and that's how I report it.
On ordering: commit `0d4427f` records the *unfavourable* pre-cleaning result and
contains no cleaning code; the threshold has a single value, never edited, and
is defined on registry-wide totals rather than on anything correlation-related.
The commits don't independently prove I fixed the rule before seeing the flip,
and I say so rather than claiming pre-registration I can't demonstrate.

### "Why drop three of the five Datadog packages?"

Because they did not exist at the start of the sample — `@datadog/browser-rum`
and `browser-logs` from Dec 2019, `datadog-ci` from Mar 2020. A package
*entering existence* adds a permanent artificial jump to a basket sum: up to
0.31 log points, concentrated in 2021Q4–2022Q3. The same rule was applied to the
control and placebo baskets, where it happened to bind on nothing. The
all-packages version is in the appendix.

### "Wouldn't differencing remove that composition effect, like it removes outages?"

No, and this is the one place where the two problems behave oppositely under the
same fix. An outage suppresses every basket at once, so it largely cancels in a
difference. Composition drift hit only the numerator, so it passes through
untouched — `|all − common|` is identically 0.1215 for `dd_abs`, `dd_rel` and
`dd_rel_plc`. I expected differencing to help and it measurably does not.

### "Your top-ranked feature lost. Doesn't that invalidate the a priori ranking?"

The opposite — it's the ranking doing its job. `dd_rel_plc` was ranked first in
LOG D24 on economic grounds, written down before Phase 4 ran, and it lost on
both targets. Had I ranked after seeing results I'd have promoted `dd_abs`,
which is precisely the selection-on-test-set error that makes a hit rate
meaningless at 13 out-of-sample points.

### "Downloads grew 112% and revenue 36%. Doesn't that break your Part 1 story?"

It does, and it's in the main body rather than in limitations for that reason.
Downloads per $m of revenue rose 346% over the sample, ρ=+0.927, near-monotonic —
the proxy decayed roughly 4.5×. I tested the obvious explanation, CI/CD re-pulls,
and it is *not* supported: the weekday/weekend ratio is flat to falling
(p=0.77). I can measure the decoupling; I can't attribute it with public data,
and I name the untested candidates rather than implying I ruled them out.

### "Why is the hyperscaler signal worse than useless?"

Intelligent Cloud growth scores 2.912 against ARIMA(1,1,0) with a bootstrap CI
of [1.671, 5.970] — significantly worse, on the wrong side of 1.0. It does hit
0.846 on direction while carrying ~3× the baseline error, which is the cleanest
illustration in the project of why a hit rate alone is a bad metric: right
direction, badly wrong magnitude. That pattern is what tracking a common cycle
looks like.

### "Only 13 out-of-sample points. Can you conclude anything?"

Not about small effects, and I don't claim to — every hit rate here is
indistinguishable from chance (binomial p ≥ 0.18 in all cases) and I say so.
What 13 points *can* support is the negative: the candidates lose to the naive
baselines by 1.03× to 2.4×, which is not a marginal miss. And the mechanism
evidence in §4 is independent of the sample size problem.

### "Why not gradient boosting or an LSTM?"

27 quarters and 13 out-of-sample predictions. Those models would fit the trend
beautifully and validate nothing — and this project's whole finding is that
trend-fitting is exactly the failure mode the simple models already exhibited.
Adding capacity would hide it.

### "How do I know there's no look-ahead in your backtest?"

It's enforced, not asserted. Features are stored as vintages with an
`available_from` date, and 13 unit tests run the guarantee, including a static
check that the feature builder never references the centred (look-ahead)
imputation variant and a dynamic one that replaces that loader with a raising
stub and rebuilds the entire panel. Disclosure dates come from the earnings 8-K,
not the 10-Q — worth up to 18 days on Q4.

### "Where does consensus fit? You didn't show it."

I couldn't source a free, citable consensus figure, so I left the field blank
and labelled it rather than approximating one — and I have not verified any
specific market reaction, so I don't assert one. The conceptual point stands
without it: Q2 2026 beat the guidance midpoint by 4.32%, and a beat against
*guidance* is not the same as a beat against an elevated *expectations* bar.
Predicting revenue direction is not sufficient for a position; the tradable
variable is beat magnitude versus consensus, which is the strongest argument
for adding a vendor consensus feed to this pipeline.

### "What would change your mind — what would make you trust a download signal?"

Three things, in order: a stable downloads-per-revenue ratio (currently ρ=+0.927
against stability), a candidate beating the *strongest* baseline while its
matched placebo fails, and that result surviving in a second ecosystem. Right
now none of the three hold. The pipeline is built to re-answer this
automatically as new quarters arrive.

---

### Numbers to have on instant recall

| | |
|---|---|
| Call | $1,188.5m, band $1,173.8–1,203.2m, YoY +34.2% |
| Guidance | $1.135–1.145bn, midpoint $1,140m, 8-K 0001628280-26-053829 |
| Trailing beat | +4.25%, sd 0.66pp, 0 of 27 quarters below midpoint |
| Best baseline | guidance + trailing beat: MAPE 5.48%, hit 69.2% |
| Grid result | 0 of 24 vs strongest baseline; 15 of 24 vs AR(1), null 0.58, p=0.002 |
| Decoupling | 21,818 → 97,228 downloads per $m, +346%, ρ=+0.927 |
| Sample | 27 usable quarters, 13–14 out-of-sample points |
| Reporting lag | median 38 days; Q4 44 days; 8-K leads 10-Q by up to 18 |
