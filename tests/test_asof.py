"""As-of discipline tests.

These are the tests that make look-ahead bias a build failure rather than a
thing to be careful about. Run with:

    .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_panel  # noqa: E402
import npm_clean  # noqa: E402
import sec_common as sc  # noqa: E402


@pytest.fixture(scope="module")
def vintages() -> pd.DataFrame:
    return build_panel.load_vintages()


# --------------------------------------------------------------- core guarantee


def test_no_feature_is_dated_after_its_asof(vintages):
    """THE test: nothing returned for an as-of date was published after it."""
    for quarter in sorted(vintages["quarter"].unique()):
        for rule in ("day30", "day45", "day60", "quarter_end", "pre_earnings"):
            asof = build_panel.decision_date(quarter, rule)
            got = build_panel.features_asof(quarter, asof, vintages)
            late = got[got["available_from"] > asof.date()]
            assert late.empty, (
                f"{quarter} @ {rule} ({asof.date()}) leaked "
                f"{len(late)} feature(s): {sorted(late['feature'])}"
            )


def test_asof_is_monotone(vintages):
    """A later as-of date can only add features, never remove or change them."""
    quarter = "2026Q2"
    early = build_panel.feature_vector(quarter, "2026-02-20", vintages)
    late = build_panel.feature_vector(quarter, "2026-08-01", vintages)
    assert set(early).issubset(set(late))
    for k, v in early.items():
        assert late[k] == v, f"{k} changed value between as-of dates"


def test_partial_quarter_features_are_not_available_early(vintages):
    """The day-45 feature cannot exist on day 44 of the quarter."""
    quarter = "2026Q2"
    start = pd.Period(quarter, freq="Q").start_time
    day44 = start + pd.Timedelta(days=43)
    day46 = start + pd.Timedelta(days=45)
    assert "dd_rel_d45" not in build_panel.feature_vector(quarter, day44, vintages)
    assert "dd_rel_d45" in build_panel.feature_vector(quarter, day46, vintages)


def test_full_quarter_feature_never_available_before_quarter_end(vintages):
    for quarter in sorted(vintages["quarter"].unique()):
        end = pd.Period(quarter, freq="Q").end_time.normalize()
        vec = build_panel.feature_vector(quarter, end, vintages)
        assert "dd_rel_full" not in vec, f"{quarter}: full-quarter feature leaked at close"


def test_guidance_not_available_before_it_was_issued(vintages):
    """Guidance for Q(t) is public only from the Q(t-1) earnings call."""
    guide = vintages[vintages["feature"] == "guide_mid_musd"]
    assert len(guide) > 20
    for _, row in guide.iterrows():
        day_before = pd.Timestamp(row["available_from"]) - pd.Timedelta(days=1)
        vec = build_panel.feature_vector(row["quarter"], day_before, vintages)
        assert "guide_mid_musd" not in vec, f"{row['quarter']}: guidance leaked"


def test_lagged_revenue_dated_from_earnings_not_period_end(vintages):
    """rev_yoy_lag1 must be dated by the 8-K, never by the prior quarter's close."""
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv", parse_dates=["known_from", "end"])
    known = dict(zip(q["quarter"], q["known_from"]))
    lag1 = vintages[vintages["feature"] == "rev_yoy_lag1"]
    assert len(lag1) > 20
    for _, row in lag1.iterrows():
        prior = str(pd.Period(row["quarter"], freq="Q") - 1)
        assert pd.Timestamp(row["available_from"]) == known[prior], (
            f"{row['quarter']}: lag1 dated {row['available_from']}, "
            f"expected {known[prior].date()}"
        )
        assert pd.Timestamp(row["available_from"]) > pd.Period(prior, freq="Q").end_time


def test_hyperscaler_features_dated_by_peer_filing(vintages):
    """Peer reads are legal only once the peer has actually filed."""
    h = pd.read_csv(sc.PROCESSED / "hyperscaler_earnings_dates.csv",
                    parse_dates=["peer_earnings_date"])
    feats = vintages[vintages["feature"].str.endswith("_reported")]
    assert len(feats) > 0
    for _, row in feats.iterrows():
        ticker = row["feature"].replace("_reported", "").upper()
        match = h[(h["quarter"] == row["quarter"]) & (h["ticker"] == ticker)]
        assert not match.empty
        assert pd.Timestamp(row["available_from"]) == match["peer_earnings_date"].iloc[0]


# ------------------------------------------- centred imputation must never leak


def test_build_panel_source_does_not_reference_centered():
    """Static check: the feature builder must not name the centred loader."""
    src = inspect.getsource(build_panel)
    assert "load_centered" not in src, "build_panel references the centred loader"
    assert "load_causal" in src


def test_feature_path_never_calls_load_centered(monkeypatch):
    """Dynamic check: poison the centred loader and rebuild the whole panel."""

    def poisoned(*args, **kwargs):
        raise AssertionError(
            "load_centered() was called on a feature path -- centred imputation "
            "uses days after the gap and is look-ahead by construction"
        )

    monkeypatch.setattr(npm_clean, "load_centered", poisoned)
    built = build_panel.build_vintages()
    assert len(built) > 0
    build_panel.live_quarter_treatments()


def test_centered_loader_is_tagged_as_forbidden():
    assert npm_clean.load_centered().attrs.get("forbidden_on_feature_path") is True
    assert npm_clean.load_causal().attrs.get("forbidden_on_feature_path") is None


def test_causal_fill_uses_only_prior_data():
    """A causal fill must be reproducible from data strictly before the gap."""
    raw = pd.read_csv(sc.PROCESSED / "npm_daily.csv", parse_dates=["date"])
    causal, _ = npm_clean.clean(raw, mode="causal")
    bad = npm_clean.bad_days()
    day = pd.Timestamp(max(bad))
    pkg = "dd-trace"
    got = causal[(causal["package"] == pkg) & (causal["date"] == day)]["downloads"].iloc[0]

    hist = raw[(raw["package"] == pkg) & (raw["date"] < day)].set_index("date")["downloads"]
    hist = hist[~hist.index.isin(bad)].astype(float)
    window = hist[hist.index >= day - pd.Timedelta(days=npm_clean.CAUSAL_LOOKBACK_DAYS)]
    expected = window[window.index.dayofweek == day.dayofweek].median()
    assert got == pytest.approx(expected)


# ------------------------------------------------------------- panel integrity


def test_panels_only_contain_reliable_quarters():
    panel = build_panel.asof_panel("pre_earnings")
    reliable = panel[panel["known_from_reliable"]]
    assert len(reliable) >= 24
    assert reliable["quarter"].is_unique


def test_live_quarter_reports_all_three_treatments():
    treat = build_panel.live_quarter_treatments()
    assert len(treat) == 3
    assert treat["imputed_share_%"].nunique() == 1  # same denominator for all
    for col in ("dd_rel_plc", "dd_rel", "dd_abs"):
        assert treat[col].notna().all(), f"{col} missing under some treatment"
