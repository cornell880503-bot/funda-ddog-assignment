"""Phase 2 -- the point-in-time (as-of) panel.

This is the module every model call must go through. Its job is to make
look-ahead bias structurally impossible rather than merely avoided by
discipline.

The design: features are not stored as a wide table indexed by quarter. They
are stored as **vintages** -- one row per (quarter, feature, value,
available_from), where `available_from` is the first date on which that exact
value could have been computed from public information. Asking for the feature
set is then a filter, not a judgement:

    features_asof(quarter="2026Q3", asof="2026-08-14")

returns only rows whose `available_from <= asof`. A feature that was not yet
computable simply is not in the result.

Where `available_from` comes from, per source:

* npm downloads   quarter_start + h days + 1 day of API latency. Verified: the
                  API's most recent day is D-1, so latency is one day.
* DDOG revenue    `known_from` in ddog_quarters.csv -- the earnings 8-K date,
                  not the 10-Q filing date and not the period end (LOG D1).
* DDOG guidance   `issued_on` -- guidance for Q(t) is public from the Q(t-1)
                  earnings call, confirmed against filing dates (LOG D12, check D).
* hyperscalers    the peer's own Item 2.02 8-K date, verified per quarter to
                  precede Datadog's in all 28 quarters, median 7 days for AMZN
                  and not the "two weeks" the brief assumed (LOG D15).

Only `npm_clean.load_causal()` is imported here. The centred variant uses days
after a gap and is therefore illegal on this path; `tests/test_asof.py` asserts
that this module never calls it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import npm_clean
import sec_common as sc

NPM_LATENCY_DAYS = 1  # verified: most recent day available from the API is D-1

# Baskets. Composition is fixed a priori on economic grounds (LOG D11):
# OpenTelemetry is excluded from the control basket because dd-trace v5
# declares it as a direct dependency, so it carries Datadog-induced traffic.
BASKETS = {
    "dd": [
        "dd-trace",
        "@datadog/browser-rum",
        "@datadog/browser-logs",
        "datadog-metrics",
        "@datadog/datadog-ci",
    ],
    "ctrl": ["newrelic", "elastic-apm-node"],  # substitutes
    "ctrl_wide": [  # robustness only: adds complements
        "newrelic",
        "elastic-apm-node",
        "@opentelemetry/api",
        "@sentry/node",
    ],
    "placebo": ["lodash", "chalk", "axios", "react"],  # no link to DDOG revenue
}

HORIZONS = [30, 45, 60, 0]  # 0 means the full quarter


def _qperiod(q: str) -> pd.Period:
    return pd.Period(q, freq="Q")


def _window(quarter: str, horizon: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Calendar window for a quarter at a given partial-quarter horizon."""
    p = _qperiod(quarter)
    start = p.start_time
    end = p.end_time.normalize() if horizon == 0 else start + pd.Timedelta(days=horizon - 1)
    return start, min(end, p.end_time.normalize())


def _available_from(quarter: str, horizon: int) -> pd.Timestamp:
    _, end = _window(quarter, horizon)
    return end + pd.Timedelta(days=NPM_LATENCY_DAYS)


def basket_sum(
    daily: pd.DataFrame, basket: str, quarter: str, horizon: int, bad: pd.DatetimeIndex
) -> float:
    """Downloads for a basket over a quarter window, under one treatment.

    `daily` is already the chosen treatment (causal / raw). `bad` is only used
    by the caller's dropped-and-rescaled variant.
    """
    start, end = _window(quarter, horizon)
    m = (
        daily["package"].isin(BASKETS[basket])
        & (daily["date"] >= start)
        & (daily["date"] <= end)
    )
    return float(daily.loc[m, "downloads"].sum())


def basket_sum_dropped(
    raw: pd.DataFrame, basket: str, quarter: str, horizon: int, bad: pd.DatetimeIndex
) -> float:
    """Outage days dropped, then rescaled by the fraction of days observed.

    No imputation at all: the quarter is estimated from its valid days only and
    scaled up to full length. Used as a sensitivity treatment for the live
    quarter, never as the point estimate.
    """
    start, end = _window(quarter, horizon)
    in_window = (raw["date"] >= start) & (raw["date"] <= end)
    valid = in_window & ~raw["date"].isin(bad)
    m = raw["package"].isin(BASKETS[basket])
    total_days = len(pd.date_range(start, end))
    valid_days = raw.loc[valid, "date"].nunique()
    if valid_days == 0:
        return float("nan")
    observed = float(raw.loc[m & valid, "downloads"].sum())
    return observed * total_days / valid_days


def yoy_log(
    daily: pd.DataFrame,
    basket: str,
    quarter: str,
    horizon: int,
    bad: pd.DatetimeIndex,
    summer=basket_sum,
) -> float:
    """Year-over-year log growth for the same day-window one year earlier.

    Comparing the first 45 days of Q against the first 45 days of Q-4 keeps the
    seasonal position identical, which a level or a quarter-on-quarter measure
    would not.
    """
    prior = str(_qperiod(quarter) - 4)
    now = summer(daily, basket, quarter, horizon, bad)
    then = summer(daily, basket, prior, horizon, bad)
    if not now or not then or now <= 0 or then <= 0:
        return float("nan")
    return float(np.log(now) - np.log(then))


def build_npm_vintages(daily: pd.DataFrame, bad: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (quarter, feature, value, available_from) for npm features."""
    quarters = sorted(
        {str(p) for p in pd.PeriodIndex(daily["date"].dt.to_period("Q").unique())}
    )
    rows = []
    for q in quarters:
        for h in HORIZONS:
            avail = _available_from(q, h)
            tag = "full" if h == 0 else f"d{h}"
            vals = {b: yoy_log(daily, b, q, h, bad) for b in BASKETS}
            feats = {
                f"dd_abs_{tag}": vals["dd"],
                f"ctrl_abs_{tag}": vals["ctrl"],
                f"dd_rel_{tag}": vals["dd"] - vals["ctrl"],
                f"plc_abs_{tag}": vals["placebo"],
                f"plc_rel_{tag}": vals["placebo"] - vals["ctrl"],
                f"dd_rel_wide_{tag}": vals["dd"] - vals["ctrl_wide"],
            }
            for name, value in feats.items():
                rows.append(
                    {
                        "quarter": q,
                        "feature": name,
                        "value": value,
                        "available_from": avail.date(),
                        "source": "npm (causal-imputed)",
                    }
                )
    return pd.DataFrame(rows)


def build_sec_vintages() -> pd.DataFrame:
    """Lagged target values and guidance, each dated by when it became public."""
    q = pd.read_csv(
        sc.PROCESSED / "ddog_quarters.csv", parse_dates=["known_from", "end"]
    )
    q = q[q["known_from_reliable"]].copy()
    g = pd.read_csv(sc.MANUAL / "guidance_template.csv", parse_dates=["issued_on"])
    g = g.rename(columns={"guided_quarter": "quarter"})

    rows = []
    by_q = {row["quarter"]: row for _, row in q.iterrows()}
    for quarter, row in by_q.items():
        p = _qperiod(quarter)
        # Lagged actuals: known from the PRIOR quarter's earnings date.
        for lag in (1, 2, 4):
            src = by_q.get(str(p - lag))
            if src is None or pd.isna(src["rev_yoy"]):
                continue
            rows.append(
                {
                    "quarter": quarter,
                    "feature": f"rev_yoy_lag{lag}",
                    "value": src["rev_yoy"],
                    "available_from": src["known_from"].date(),
                    "source": f"SEC 8-K/10-Q, {src['quarter']} print",
                }
            )
        # Revenue level of Q-4, needed to turn a growth forecast into dollars.
        src4 = by_q.get(str(p - 4))
        if src4 is not None:
            rows.append(
                {
                    "quarter": quarter,
                    "feature": "rev_musd_lag4",
                    "value": src4["revenue_musd"],
                    "available_from": src4["known_from"].date(),
                    "source": f"SEC, {src4['quarter']} print",
                }
            )

    # Guidance for Q(t), public from the Q(t-1) earnings call.
    for _, row in g.iterrows():
        if pd.isna(row["guide_low_musd"]):
            continue
        mid = (row["guide_low_musd"] + row["guide_high_musd"]) / 2
        for name, value in (
            ("guide_mid_musd", mid),
            ("guide_low_musd", row["guide_low_musd"]),
            ("guide_high_musd", row["guide_high_musd"]),
        ):
            rows.append(
                {
                    "quarter": row["quarter"],
                    "feature": name,
                    "value": value,
                    "available_from": row["issued_on"].date(),
                    "source": f"8-K EX-99.1 {row['accession']} (UNVERIFIED)",
                }
            )
    return pd.DataFrame(rows)


def build_hyperscaler_vintages() -> pd.DataFrame:
    """Peer reporting dates. Values are not in XBRL (LOG D15); timing is."""
    path = sc.PROCESSED / "hyperscaler_earnings_dates.csv"
    if not path.exists():
        return pd.DataFrame(columns=["quarter", "feature", "value", "available_from", "source"])
    h = pd.read_csv(path, parse_dates=["peer_earnings_date"])
    rows = [
        {
            "quarter": r["quarter"],
            "feature": f"{r['ticker'].lower()}_reported",
            "value": 1.0,
            "available_from": r["peer_earnings_date"].date(),
            "source": f"{r['ticker']} 8-K {r['peer_accn']}",
        }
        for _, r in h.iterrows()
    ]
    return pd.DataFrame(rows)


def build_vintages() -> pd.DataFrame:
    daily = npm_clean.load_causal()
    bad = npm_clean.bad_days()
    frames = [
        build_npm_vintages(daily, bad),
        build_sec_vintages(),
        build_hyperscaler_vintages(),
    ]
    out = pd.concat([f for f in frames if len(f)], ignore_index=True)
    out = out.dropna(subset=["value"])
    out["available_from"] = pd.to_datetime(out["available_from"]).dt.date
    return out.sort_values(["quarter", "available_from", "feature"]).reset_index(drop=True)


# --------------------------------------------------------------- as-of access


def features_asof(
    quarter: str, asof: str | pd.Timestamp, vintages: pd.DataFrame | None = None
) -> pd.DataFrame:
    """The legal feature set for `quarter` as of `asof`. The only accessor.

    Returns rows whose available_from <= asof. Nothing else in this project may
    read the vintage table directly.
    """
    if vintages is None:
        vintages = load_vintages()
    asof = pd.Timestamp(asof).date()
    m = (vintages["quarter"] == quarter) & (vintages["available_from"] <= asof)
    out = vintages[m].copy()
    out["asof"] = asof
    return out.sort_values("feature").reset_index(drop=True)


def feature_vector(quarter: str, asof, vintages: pd.DataFrame | None = None) -> dict:
    df = features_asof(quarter, asof, vintages)
    return dict(zip(df["feature"], df["value"]))


def decision_date(quarter: str, rule: str) -> pd.Timestamp:
    """Map a decision rule to an as-of date for one quarter.

    day30/45/60  -- mid-quarter calls, while the trade is still actionable
    quarter_end  -- everything through the close, nothing after
    pre_earnings -- the day before Datadog reports (brief section 4)
    """
    p = _qperiod(quarter)
    if rule.startswith("day"):
        return p.start_time + pd.Timedelta(days=int(rule[3:]) - 1 + NPM_LATENCY_DAYS)
    if rule == "quarter_end":
        return p.end_time.normalize() + pd.Timedelta(days=NPM_LATENCY_DAYS)
    if rule == "pre_earnings":
        q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv", parse_dates=["known_from"])
        row = q[q["quarter"] == quarter]
        if row.empty or pd.isna(row["known_from"].iloc[0]):
            # Quarter not yet reported: fall back to the median 38-day lag.
            return p.end_time.normalize() + pd.Timedelta(days=38)
        return row["known_from"].iloc[0] - pd.Timedelta(days=1)
    raise ValueError(f"unknown rule {rule!r}")


def asof_panel(rule: str, vintages: pd.DataFrame | None = None) -> pd.DataFrame:
    """Wide panel: one row per quarter, features legal at that quarter's decision date."""
    if vintages is None:
        vintages = load_vintages()
    targets = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    rows = []
    for quarter in sorted(vintages["quarter"].unique()):
        asof = decision_date(quarter, rule)
        vec = feature_vector(quarter, asof, vintages)
        if not vec:
            continue
        t = targets[targets["quarter"] == quarter]
        rows.append(
            {
                "quarter": quarter,
                "asof": asof.date(),
                "rev_yoy": t["rev_yoy"].iloc[0] if len(t) else np.nan,
                "revenue_musd": t["revenue_musd"].iloc[0] if len(t) else np.nan,
                "known_from_reliable": bool(t["known_from_reliable"].iloc[0]) if len(t) else False,
                **vec,
            }
        )
    return pd.DataFrame(rows)


def load_vintages() -> pd.DataFrame:
    path = sc.PROCESSED / "feature_vintages.csv"
    if not path.exists():
        raise FileNotFoundError("run `python src/build_panel.py` first")
    df = pd.read_csv(path)
    df["available_from"] = pd.to_datetime(df["available_from"]).dt.date
    return df


# ------------------------------------------------------- live-quarter treatments


def live_quarter_treatments(quarter: str | None = None, asof: str | None = None) -> pd.DataFrame:
    """The live quarter's signal under all three outage treatments.

    The dashboard headline must show the spread, not just the point estimate:
    four of the live quarter's elapsed days are API outages, so the choice of
    treatment is a real source of uncertainty and hiding it would misrepresent
    the confidence of the call.
    """
    asof_ts = pd.Timestamp(asof) if asof else pd.Timestamp.today().normalize()
    quarter = quarter or str(asof_ts.to_period("Q"))
    p = _qperiod(quarter)
    elapsed = (min(asof_ts, p.end_time.normalize()) - p.start_time).days + 1
    horizon = elapsed - NPM_LATENCY_DAYS

    bad = npm_clean.bad_days()
    causal = npm_clean.load_causal()
    raw = npm_clean.load_raw_with_zeros()

    n_bad_in_q = sum(1 for d in bad if p.start_time <= d <= asof_ts)
    rows = []
    for name, frame, summer in (
        ("causal-imputed (point estimate)", causal, basket_sum),
        ("dropped days, rescaled", raw, basket_sum_dropped),
        ("raw, outage zeros kept", raw, basket_sum),
    ):
        rows.append(
            {
                "treatment": name,
                "quarter": quarter,
                "days_elapsed": elapsed,
                "days_used": horizon,
                "dd_abs_yoy_log": yoy_log(frame, "dd", quarter, horizon, bad, summer),
                "ctrl_abs_yoy_log": yoy_log(frame, "ctrl", quarter, horizon, bad, summer),
                "dd_rel_yoy_log": yoy_log(frame, "dd", quarter, horizon, bad, summer)
                - yoy_log(frame, "ctrl", quarter, horizon, bad, summer),
                "plc_rel_yoy_log": yoy_log(frame, "placebo", quarter, horizon, bad, summer)
                - yoy_log(frame, "ctrl", quarter, horizon, bad, summer),
                "imputed_days": n_bad_in_q,
                "imputed_share_%": n_bad_in_q / elapsed * 100,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    vintages = build_vintages()
    out = sc.PROCESSED / "feature_vintages.csv"
    vintages.to_csv(out, index=False)
    print(f"Wrote {out.relative_to(sc.REPO)}  "
          f"({len(vintages):,} vintage rows, {vintages['feature'].nunique()} features, "
          f"{vintages['quarter'].nunique()} quarters)\n")

    pd.set_option("display.width", 220)
    for rule in ("day45", "quarter_end", "pre_earnings"):
        panel = asof_panel(rule, vintages)
        panel = panel[panel["known_from_reliable"]]
        path = sc.PROCESSED / f"panel_{rule}.csv"
        panel.to_csv(path, index=False)
        n_feat = panel.drop(columns=["quarter", "asof", "rev_yoy", "revenue_musd",
                                     "known_from_reliable"]).notna().sum(axis=1)
        print(f"{rule:<13} -> {path.name}  rows={len(panel)}  "
              f"median features/row={int(n_feat.median())}")

    print("\nLive quarter, three outage treatments:")
    print(live_quarter_treatments().round(4).to_string(index=False))


if __name__ == "__main__":
    main()
