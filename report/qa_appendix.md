# Q&A appendix — one answer per decision point

Five minutes is two or three questions. These are the ones a buy-side reviewer
is most likely to reach for, each already resolved during the work. Answer in
two sentences, then stop.

---

### "Your headline uses no alternative data. Isn't that a failed assignment?"

The assignment asks for evidence and for honesty about what the data does and
does not support, and this is what it supports. I tested two signals across 24
cells on two revenue targets plus two more target metrics, with matched
controls throughout; none beat a correctly specified naive baseline, and I can
show exactly why. Reporting a signal-weighted estimate would mean reporting a
relationship my own validation rejected.

### "npm is the wrong proxy. Datadog's agent is Go, shipped via Docker and APT — you tested a minor SDK and generalised."

That is the right criticism and I have narrowed the claim to match. Docker Hub
`datadog/agent` has 11.25bn cumulative pulls against 1.13bn lifetime downloads
for the npm basket — roughly **10x the volume in a channel I could not test**,
because Docker Hub publishes only a lifetime counter with no time series and no
per-tag split, so it cannot be backfilled. The finding is therefore not
"alternative data cannot predict Datadog"; it is that the freely and
historically observable slice is the wrong slice, and the right slice is not
retrospectively observable. The forward fix is one API call a day, which is now
the first item in productisation.

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

### "The 8-quarter trailing window wasn't pre-registered. You held the signals to walk-forward but let the baseline see the whole sample."

Correct, and flagging it as post hoc was not sufficient — so I replaced it. The
baseline now selects its window from {4, 6, 8, 12, expanding} by a nested
walk-forward **inside the training set only**, at every step. Removing the
snooping made the baseline *better*, not worse — RMSE 0.0229 → 0.0200, MAPE
5.48% → 4.10% — so the bar for the signals went up. And for the live quarter
the fair rule independently selects 8 quarters, so the published call is
unchanged; only its derivation is now legitimate.

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

### "Your decoupling finding ignores SaaS economics — volume discounts, private registries, cross-sell."

I tested those rather than assuming them away. Normalising by the disclosed
$100k+ ARR customer count: revenue per large customer rose **+67%** — that is
exactly the cross-sell and tiering effect, and it is real — but downloads per
large customer rose **+644%**, roughly ten times faster. So per-customer
monetisation explains a minority of the gap. Private-registry mirroring would
push downloads per customer *down*, so it cannot explain a 644% rise either.
The decoupling survives the correct normalisation; the critique's mechanism is
retained as a secondary contributor, not dismissed. CI/CD re-pulls also fail
the test: weekday/weekend ratio 6.39 → 5.61, p=0.77.

### "Why is the hyperscaler signal worse than useless?"

Intelligent Cloud growth scores 2.912 against ARIMA(1,1,0) with a bootstrap CI
of [1.671, 5.970] — significantly worse, on the wrong side of 1.0. It does hit
0.846 on direction while carrying ~3× the baseline error, which is the cleanest
illustration in the project of why a hit rate alone is a bad metric: right
direction, badly wrong magnitude. That pattern is what tracking a common cycle
looks like.

### "Only 13 out-of-sample points. Isn't 'no significant result' just low power — absence of evidence, not evidence of absence?"

Exactly right, so I measured the power rather than conceding the point. Given
the observed baseline errors, a Diebold–Mariano test at n=13 detects a
competing model with 5% lower RMSE only **6%** of the time, and 10% lower
**15%** of the time. **A genuine modest edge would have been missed roughly
85–90% of the time**, so "0 of 24" *bounds* the effect size rather than showing
it is zero — and the report says that in those words. The part that is not a
power problem: the observed cells sit at ratios of **1.05 to 2.65**, consistent
large degradation on the wrong side of parity. Missing a small positive edge is
low power; measuring a large negative one is measurement.

### "You never tested billings, RPO, NRR or large-customer growth — the brief names them."

A real gap in the first version, now closed. `cust_yoy` ($100k+ ARR customers,
28 quarters): 0 of 12 cells beat the baseline, best **1.049**. `billings_yoy`
(revenue + change in deferred revenue): 0 of 12, n_oos=7, reported as
underpowered rather than as a result. `rpo_yoy`: 20 quarters cannot support a
walk-forward. NRR is not disclosed as a number in the 8-K exhibits, so it is
excluded rather than approximated. The customer test also has a point to it —
see the next question.

### "Downloads are a count and revenue is dollar-weighted. Isn't that just bad feature engineering?"

It is a real mismatch, and I turned it into a falsifiable prediction: if the
count-vs-dollars gap is what breaks the mapping, a count-type target should fit
better. It does — against $100k+ customer growth the best cell is **1.049**
versus **1.137** against revenue growth, the closest any signal came to a
baseline in this project, and the matched controls fail on those cells (1.69 to
1.83), so the residual edge is attributable. Directionally the critique is
correct. It is still a loss, at n=11.

### "You tested the signal against revenue, but alt data is used to predict the surprise around guidance, not to replace it."

Half of that I had done — `beat_vs_guide` is a target in the grid, and it is the
surprise. The half I had not done is the one that matters: the features were
raw, so they competed with information guidance already carried. I re-ran every
cell with the feature residualised against guidance-implied growth using
train-only coefficients. Result: **0 of 24 again, and the best cell worsens from
1.075 to 1.323** — stripping out what guidance implies leaves less, not more.

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
| Best baseline | guidance + out-of-sample-selected window: MAPE 4.10%, hit 76.9% |
| Grid result | 0 of 24 vs strongest baseline; 0 of 24 orthogonalised; 15 of 24 vs AR(1), null 0.58, p=0.002 |
| Other targets | customer growth best 1.049 (n=11); billings 1.106 (n=7); RPO untestable; NRR not disclosed |
| Observability | Docker `datadog/agent` 11.25bn pulls vs npm basket 1.13bn — 10x, no history |
| Power | detects r=0.95 6% of the time, r=0.90 15% |
| Decoupling | 21,818 → 97,228 downloads per $m, +346%, ρ=+0.927 |
| Sample | 27 usable quarters, 13–14 out-of-sample points |
| Reporting lag | median 38 days; Q4 44 days; 8-K leads 10-Q by up to 18 |
