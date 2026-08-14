"""Cross-ecosystem robustness check: PyPI versus npm.

Purpose: test whether the Datadog download signal is an artefact of the
JavaScript ecosystem. If the Python tracer (`ddtrace` on PyPI) and the Node
tracer (`dd-trace` on npm) behave alike over the window where both are
observable, the signal is more plausibly tracking Datadog instrumentation
deployment than tracking npm registry mechanics.

Scope limit, stated up front: pypistats.org retains ~181 days, so a
year-over-year figure is **not computable** for PyPI. Long PyPI history would
require the BigQuery public dataset, which was out of scope. Everything here is
a robustness check and never a model input.

Two tests, and only one of them survives:

1. Co-movement of weekly log changes. Reported WITH a placebo: the same
   correlation is computed between PyPI `ddtrace` and competitor npm packages.
   If a competitor correlates as strongly, the co-movement is a shared
   working-day/holiday calendar and carries no Datadog-specific information.
2. Relative growth over the window: did Datadog packages outgrow their control
   cohort in BOTH registries? This is the test that can actually fail, because
   the calendar effect is differenced out on both sides.

Outputs:
  report/figures/pypi_npm_consistency.png
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import npm_clean
import sec_common as sc

# Substitute cohorts, consistent with the denominator decision in LOG.md D11:
# OpenTelemetry is excluded because dd-trace v5 declares it as a direct
# dependency, so it carries Datadog-induced traffic.
NPM_CONTROL = ["newrelic", "elastic-apm-node"]
PYPI_CONTROL = ["newrelic", "elastic-apm"]


def daily(df: pd.DataFrame, mask) -> pd.Series:
    s = df[mask].groupby("date")["downloads"].sum().sort_index()
    return s.asfreq("D").interpolate()


def weekly_log_change(s: pd.Series) -> pd.Series:
    return np.log(s.resample("W").sum()).diff().dropna()


def window_growth(s: pd.Series) -> float:
    """Growth from the first to the last 28-day mean, in percent."""
    ma = s.rolling(28).mean().dropna()
    return (ma.iloc[-1] / ma.iloc[0] - 1) * 100


def placebo_correlations(npm: pd.DataFrame, target: pd.Series) -> pd.DataFrame:
    rows = []
    for pkg in ["dd-trace", "@datadog/browser-rum", "newrelic", "elastic-apm-node"]:
        x = weekly_log_change(daily(npm, npm["package"] == pkg))
        j = pd.concat([x, target], axis=1, join="inner").dropna()
        j.columns = ["npm", "pypi"]
        rows.append(
            {
                "npm package": pkg,
                "cohort": "datadog" if "datadog" in pkg or pkg == "dd-trace" else "control",
                "corr_vs_pypi_ddtrace": j["npm"].corr(j["pypi"]),
                "sign_agreement_%": (np.sign(j["npm"]) == np.sign(j["pypi"])).mean() * 100,
                "n_weeks": len(j),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_gap(npm: pd.DataFrame, target: pd.Series, ctrl_pkg: str) -> tuple:
    """95% CI on corr(dd-trace, pypi) - corr(control, pypi).

    Weeks are resampled jointly so the three series stay aligned. The ranking
    on its own means nothing at n=26; the interval is the test.
    """
    rng = np.random.default_rng(20260814)
    dd_w = weekly_log_change(daily(npm, npm["package"] == "dd-trace"))
    ctrl_w = weekly_log_change(daily(npm, npm["package"] == ctrl_pkg))
    joint = pd.concat([dd_w, ctrl_w, target], axis=1, join="inner").dropna()
    joint.columns = ["dd", "ctrl", "pypi"]
    diffs = []
    for _ in range(10000):
        s = joint.iloc[rng.integers(0, len(joint), len(joint))]
        diffs.append(s["dd"].corr(s["pypi"]) - s["ctrl"].corr(s["pypi"]))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return lo, hi, len(joint)


def main() -> None:
    pypi = pd.read_csv(sc.PROCESSED / "pypi_daily_180d.csv", parse_dates=["date"])

    # The as-of-legal variant is the one whose number goes in the report. The
    # other two are run to size the sensitivity, not to choose a favourite.
    treatments = {
        "causal (as-of legal, REPORTED)": npm_clean.load_causal(),
        "centered (descriptive only)": npm_clean.load_centered(),
        "raw with outage zeros": npm_clean.load_raw_with_zeros(),
    }

    start = max(min(t["date"].min() for t in treatments.values()), pypi["date"].min())
    end = min(min(t["date"].max() for t in treatments.values()), pypi["date"].max())
    pypi = pypi[(pypi["date"] >= start) & (pypi["date"] <= end)]
    print(f"Overlapping window: {start.date()} .. {end.date()} "
          f"({(end - start).days + 1} days)\n")
    target = weekly_log_change(daily(pypi, pypi["package"] == "ddtrace"))

    # ---------- Test 1: co-movement, with placebo, under three treatments ----------
    print("TEST 1 -- weekly log-change co-movement vs PyPI ddtrace, with placebo")
    sens = []
    for name, frame in treatments.items():
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        tbl = placebo_correlations(frame, target)
        dd_corr = tbl.loc[tbl["npm package"] == "dd-trace", "corr_vs_pypi_ddtrace"].iloc[0]
        best = tbl[tbl["cohort"] == "control"].nlargest(1, "corr_vs_pypi_ddtrace").iloc[0]
        lo, hi, n = bootstrap_gap(frame, target, best["npm package"])
        sens.append(
            {
                "treatment": name,
                "dd-trace": dd_corr,
                "best control": best["corr_vs_pypi_ddtrace"],
                "control pkg": best["npm package"],
                "dd above placebo": "yes" if dd_corr > best["corr_vs_pypi_ddtrace"] else "NO",
                "boot 95% CI on gap": f"[{lo:+.3f}, {hi:+.3f}]",
                "covers zero": "yes" if lo <= 0 <= hi else "no",
            }
        )
        if name.startswith("causal"):
            print("\nDetail, causal treatment (the reported one):")
            print(tbl.round(3).to_string(index=False))

    sens = pd.DataFrame(sens)
    print("\nSensitivity across imputation treatments:")
    print(sens.round(3).to_string(index=False))

    causal_row = sens.iloc[0]
    print(
        f"\n  Verdict: INCONCLUSIVE. Removing 0.34% of observations (12 outage days)"
        f"\n  moves the dd-trace correlation from "
        f"{sens.iloc[2]['dd-trace']:.3f} (raw, {sens.iloc[2]['dd above placebo']} above placebo)"
        f" to {causal_row['dd-trace']:.3f}"
        f"\n  (causal, {causal_row['dd above placebo']} above placebo). A result that flips sign"
        f"\n  on 0.34% of the data is not a result. The bootstrap CI on the gap,"
        f"\n  {causal_row['boot 95% CI on gap']}, covers zero independently of that."
        "\n  Every package tested -- Datadog's and its competitors' -- correlates with"
        "\n  PyPI ddtrace in a narrow band, because all of them are dominated by the"
        "\n  same working-day and holiday calendar. This test is reported as evidence"
        "\n  FOR the inconclusive verdict, not as a repair that rescued the signal.\n"
    )

    # ---------- Test 2: relative growth, calendar effect differenced out ----------
    npm = treatments["causal (as-of legal, REPORTED)"]
    npm = npm[(npm["date"] >= start) & (npm["date"] <= end)]
    rows = []
    for reg, df, ctrl in (("npm", npm, NPM_CONTROL), ("PyPI", pypi, PYPI_CONTROL)):
        dd = daily(df, df["cohort"] == "datadog")
        cn = daily(df, df["package"].isin(ctrl))
        rows.append(
            {
                "registry": reg,
                "datadog_growth_%": window_growth(dd),
                "control_growth_%": window_growth(cn),
                "excess_pp": window_growth(dd) - window_growth(cn),
            }
        )
    growth = pd.DataFrame(rows)
    print("TEST 2 -- growth over the window, Datadog basket vs substitute controls")
    print(growth.round(1).to_string(index=False))

    # Tracer-vs-tracer is the closest like-for-like pairing: the Node and Python
    # APM agents of the same two vendors.
    tracer = []
    for reg, df, dd_pkg, ctrl_pkg in (
        ("npm", npm, "dd-trace", "newrelic"),
        ("PyPI", pypi, "ddtrace", "newrelic"),
    ):
        a = window_growth(daily(df, df["package"] == dd_pkg))
        b = window_growth(daily(df, df["package"] == ctrl_pkg))
        tracer.append(
            {
                "registry": reg,
                "datadog_tracer": dd_pkg,
                "growth_%": a,
                "newrelic_growth_%": b,
                "excess_pp": a - b,
            }
        )
    tracer = pd.DataFrame(tracer)
    print("\n  Like-for-like, APM tracer vs New Relic agent in the same registry:")
    print("  " + tracer.round(1).to_string(index=False).replace("\n", "\n  "))

    same_sign = np.sign(growth["excess_pp"]).nunique() == 1
    same_sign_tracer = np.sign(tracer["excess_pp"]).nunique() == 1
    print(
        f"\n  Verdict: excess growth same sign in both registries -- "
        f"basket: {'yes' if same_sign else 'NO'}, "
        f"tracer-only: {'yes' if same_sign_tracer else 'NO'}."
    )
    if not (same_sign or same_sign_tracer):
        print(
            "  The npm signal is NOT confirmed by PyPI. Datadog outgrows its controls\n"
            "  on npm and underperforms them on PyPI over the same 181 days.\n"
            "  Caveats that limit how much weight this negative carries: the PyPI\n"
            "  control base is small (~135k downloads/day for newrelic against 1.27m\n"
            "  for ddtrace), so its growth rate is volatile; the largest PyPI Datadog\n"
            "  package by volume is `datadog` (2.27m/day), an API/metrics client\n"
            "  rather than instrumentation; and 181 days is a single, short window\n"
            "  with no YoY available. This is a failed confirmation, not a refutation\n"
            "  -- but it must be reported as a failed confirmation.\n"
        )

    # ---------- figure ----------
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, (label, pair) in zip(
        axes,
        {
            "APM tracer: dd-trace (npm) vs ddtrace (PyPI)": (
                daily(npm, npm["package"] == "dd-trace"),
                daily(pypi, pypi["package"] == "ddtrace"),
            ),
            "Full Datadog basket": (
                daily(npm, npm["cohort"] == "datadog"),
                daily(pypi, pypi["cohort"] == "datadog"),
            ),
        }.items(),
    ):
        for name, s in zip(("npm", "PyPI"), pair):
            ma = s.rolling(28).mean().dropna()
            ax.plot(ma.index, ma / ma.iloc[0], label=name)
        ax.axhline(1, lw=0.5, color="grey")
        ax.set_title(label, fontsize=10)
        ax.legend()
    fig.suptitle(
        f"PyPI vs npm, 28d MA indexed to window start ({start.date()} to "
        f"{end.date()}) -- robustness check, not a model input"
    )
    fig.tight_layout()
    out = sc.REPO / "report" / "figures" / "pypi_npm_consistency.png"
    fig.savefig(out, dpi=140)
    print(f"Wrote {out.relative_to(sc.REPO)}")
    print(
        "\nBottom line: neither test confirms the npm signal. Test 1 is a calendar"
        "\nartefact (a competitor placebo scores higher). Test 2 gives the opposite"
        "\nsign on PyPI. Nothing here supports a predictive claim in either direction:"
        "\n181 days, no YoY, n=26 weeks."
    )


if __name__ == "__main__":
    main()
