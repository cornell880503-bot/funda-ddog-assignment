# DDOG Nowcast

Alternative-data nowcasting of Datadog (NASDAQ: DDOG) quarterly revenue, plus a
live divergence monitor.

**The headline finding is negative, and that is the result.** Across 24
signal × window constructions, **0 beat the strongest naive baseline out of
sample** — and 0 again after orthogonalising the features against guidance. The
constructions that appear to beat an AR(1) are fitting drift: a bare time index
beats AR(1) too, at 0.896. What the alternative data supports is a monitor, not
a forecast.

The number this repo actually stands behind uses **no alternative data at all**:
guidance midpoint × (1 + mean beat over an out-of-sample-selected window), which
gives **$1,188.5m** for 2026Q3 (95% band $1,173.8m–$1,203.2m) at MAPE 4.10% and a
76.9% directional hit rate.

## Scope and compliance

Every figure traces to a cached raw response or a cited SEC accession number.
Sources are public SEC filings (EDGAR XBRL and Item 2.02 8-K exhibits) and public,
unauthenticated APIs — the npm registry, pypistats.org, Docker Hub. **No material
non-public information. No scraping behind a login or against robots.txt.**

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

SEC rejects requests without a contact address in the User-Agent, so the EDGAR
stages need this set. There is no default — set your own:

```bash
export SEC_CONTACT_EMAIL="you@example.com"
```

The npm and rendering stages do not touch EDGAR and run without it.

## Refreshing the dashboard

**This is the command you want day to day:**

```bash
python refresh.py
```

Roughly 40 seconds. It tops up npm downloads, redetects outages, rebuilds the
as-of vintages, recomputes the tracking call, and re-renders both dashboards. It
prints the live reading and warns if the imputed share of the quarter goes above
20%. npm restates recent days for a while, so it re-pulls a 14-day tail and
de-duplicates rather than appending blindly; widen it with `--days 30`.

```bash
python refresh.py --days 30    # longer tail
python refresh.py --full       # delegate to the complete pipeline
```

**Why not run everything daily.** `run_all.py` re-runs model selection,
walk-forward validation, the permutation null and the bootstrap — around twenty
stages and several minutes. None of it moves day to day: those results change
when a new quarter reports, not when a new day of downloads lands. Re-fitting
daily on data that grew by one day is also how a stable finding quietly turns
into a drifting one.

**After a quarter reports**, run the full pipeline instead:

```bash
python run_all.py          # cached raw responses where present
python run_all.py --force  # re-pull every API (slow; hits SEC and npm)
python run_all.py --check  # verify existing outputs only
```

### Automating it

```bash
# refresh every weekday at 09:00 — crontab -e
0 9 * * 1-5 cd /path/to/ddog-nowcast && .venv/bin/python refresh.py >> refresh.log 2>&1
```

## Outputs

| Artefact | Path |
|---|---|
| Dashboard (English) | `dashboard/index.html` |
| Dashboard (中文) | `report-zh/dashboard.html` |
| Slides (English) | `report/slides.md` |
| Slides (中文) | `report-zh/slides.md` |
| Written report | `report/report.md`, `report-zh/report.md` |
| Decision log | `LOG.md` |

Dashboards are self-contained single files — all data is inlined at render time,
so they open offline by double-clicking and need no server.

## Repository layout

```
src/          fetchers, cleaning, panel construction, models, renderers
tests/        as-of / look-ahead regression tests
data/raw/     cached API responses and filing text (JSON is gitignored)
data/processed/  derived CSVs -- every later stage reads only from here
data/manual/  hand-verified guidance figures
report/, report-zh/   deliverables
prep/, prep-zh/       Q&A and presenter notes -- not deliverables
notebooks/    exploration
LOG.md        decision record, D1-D44, including rejected options
```

The separation matters: fetchers write `data/raw/` and `data/processed/`, and
every later stage reads only from `data/processed/`, never from an API. With the
cache in place the whole pipeline is offline and deterministic (seeds fixed in
`model_walkforward.SEED`).

## Method notes

- **Point-in-time panel.** Features are dated by when they were *observable*.
  `available_from` comes from the Item 2.02 8-K, not the 10-Q, because the
  revenue print is public at the 8-K.
- **Causal imputation only.** Outage gaps are filled backward-only from the prior
  42 days. A centred variant exists for diagnostics and is asserted in
  `tests/test_asof.py` to be unreachable from any feature path.
- **Matched negative controls.** A placebo basket of general-purpose JavaScript
  packages runs through the *identical* pipeline. It is not a robustness
  afterthought — when the placebo leans as hard as the signal, the ecosystem is
  what moved. The strongest single result in the project is a placebo that
  passed: legal boilerplate in the 8-K beats management's own language on every
  comparison, because it proxies time.
- **Nested walk-forward selection.** Window length is chosen inside the training
  set, so the baseline the signals are scored against is not itself snoopable.

## Testing

```bash
.venv/bin/python -m pytest tests -q     # 13 as-of / look-ahead tests
python run_all.py --check               # tests plus headline figure verification
```

The renderers self-check: the Chinese build executes both pages' JavaScript and
fails if it renders fewer blocks than the English build, and refuses to ship a
translated value that the template branches on. That guard exists because an
earlier Chinese build silently dropped eight of ten panels — the file was
complete and correctly translated, it just stopped executing partway down.
