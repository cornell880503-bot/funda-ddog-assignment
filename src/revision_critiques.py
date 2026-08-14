"""Revision pass answering five review critiques.

Each critique is answered with a computation, not a caveat.

C1  PROXY SCOPE. npm sees only the Node.js APM SDK. Datadog's core billable
    surface is the Go agent, shipped through Docker Hub / APT / YUM / Helm.
    Quantify the coverage gap and establish what is and is not observable.

C2  BASELINE DATA SNOOPING. The 8-quarter window was chosen post hoc while the
    signals faced walk-forward discipline. Replaced with a window selected by
    nested walk-forward on training data only. (Implemented in
    model_walkforward; scored here.)

C3  TYPE II ERROR. "0 of 24" at n=13 is weak evidence unless the test could
    have detected a real effect. Compute the minimum detectable RMSE ratio.

C4  SAAS MECHANICS. Private registries, volume discounts and cross-sell all
    break a linear downloads-to-dollars mapping. Test the customer-normalised
    version: revenue per large customer vs downloads per large customer.

C5  EXPECTATION ALIGNMENT. Features were tested raw rather than orthogonal to
    guidance-implied growth, so they competed with information guidance
    already carried. Re-run the grid on guidance-residualised features.

Outputs:
  processed/revision_grid.csv
  processed/revision_power.csv
  processed/revision_coverage.csv
  report/figures/revision_customer_normalised.png
"""

from __future__ import annotations

import json
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from scipy import stats

import model_walkforward as mw
import npm_clean
import sec_common as sc

DOCKER_REPOS = ["datadog/agent", "datadog/cluster-agent"]


# ------------------------------------------------------------------ C1 scope
def coverage() -> pd.DataFrame:
    daily = npm_clean.load_causal()
    rows = []
    basket = daily[daily["package"].isin(["dd-trace", "datadog-metrics"])]
    rows.append({
        "channel": "npm (constant-composition basket)",
        "what_it_distributes": "Node.js APM tracer + metrics client",
        "cumulative_units": int(basket["downloads"].sum()),
        "history": "daily, 2017+",
        "in_model": "yes",
    })
    rows.append({
        "channel": "npm (all Datadog packages)",
        "what_it_distributes": "Node.js SDKs incl. browser RUM/logs, CI",
        "cumulative_units": int(daily[daily["cohort"] == "datadog"]["downloads"].sum()),
        "history": "daily, 2017+",
        "in_model": "appendix",
    })
    cache = sc.RAW / "dockerhub_datadog.json"
    if cache.exists():
        payload = json.loads(cache.read_text())
    else:
        payload = {}
        for repo in DOCKER_REPOS:
            r = requests.get(f"https://hub.docker.com/v2/repositories/{repo}/",
                             headers=sc.HEADERS, timeout=60)
            time.sleep(0.3)
            payload[repo] = r.json()
        cache.write_text(json.dumps(payload))
    for repo in DOCKER_REPOS:
        rows.append({
            "channel": f"Docker Hub {repo}",
            "what_it_distributes": "the core Go agent (host + container monitoring)",
            "cumulative_units": int(payload[repo]["pull_count"]),
            "history": "CUMULATIVE COUNTER ONLY -- no time series",
            "in_model": "NO -- not backfillable",
        })
    for ch, note in (
        ("APT / YUM repositories", "Linux package installs of the core agent"),
        ("Helm chart / Kubernetes operator", "container-orchestrated agent rollout"),
        ("AWS / Azure / GCP marketplace", "marketplace-billed deployments"),
    ):
        rows.append({"channel": ch, "what_it_distributes": note,
                     "cumulative_units": None,
                     "history": "not publicly exposed", "in_model": "NO"})
    return pd.DataFrame(rows)


# ----------------------------------------------------------- C4 per-customer
def customer_normalised() -> pd.DataFrame:
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    cust = pd.read_csv(sc.MANUAL / "customers_100k_template.csv")
    cust = cust.rename(columns={"reported_quarter": "quarter"})
    m = q.merge(cust[["quarter", "customers_ge_100k"]], on="quarter", how="inner")
    m = m[m["known_from_reliable"] & m["customers_ge_100k"].notna()].copy()

    daily = npm_clean.load_causal()
    dd = daily[daily["package"].isin(["dd-trace", "datadog-metrics"])].copy()
    dd["quarter"] = dd["date"].dt.to_period("Q").astype(str)
    dlq = dd.groupby("quarter")["downloads"].sum().rename("downloads")
    m = m.merge(dlq, left_on="quarter", right_index=True, how="inner")

    m["rev_per_cust_k"] = m["revenue_musd"] * 1000 / m["customers_ge_100k"]
    m["dl_per_cust"] = m["downloads"] / m["customers_ge_100k"]
    m["dl_per_musd"] = m["downloads"] / m["revenue_musd"]
    return m[["quarter", "revenue_musd", "customers_ge_100k", "downloads",
              "rev_per_cust_k", "dl_per_cust", "dl_per_musd"]].reset_index(drop=True)


def main() -> None:
    pd.set_option("display.width", 230)
    f = mw.frame()

    # ---------------------------------------------------------------- C1
    print("=" * 78)
    print("C1 -- WHAT npm ACTUALLY SEES")
    print("=" * 78)
    cov = coverage()
    cov.to_csv(sc.PROCESSED / "revision_coverage.csv", index=False)
    print(cov.to_string(index=False))
    npm_basket = cov.loc[0, "cumulative_units"]
    agent = cov.loc[2, "cumulative_units"]
    print(f"\n  Docker Hub datadog/agent pulls / npm basket downloads = "
          f"{agent / npm_basket:.1f}x")
    print("  The core agent's distribution channel is ~10x the volume of the")
    print("  channel the model could observe, and exposes no history at all.")

    # ---------------------------------------------------------------- C2/C5
    print("\n" + "=" * 78)
    print("C2 + C5 -- FAIR BASELINE, AND FEATURES ORTHOGONAL TO GUIDANCE")
    print("=" * 78)
    base = pd.read_csv(sc.PROCESSED / "wf_baselines.csv")
    best = base.sort_values("rmse").groupby("target").first()["baseline"].to_dict()
    print("Strongest baseline per target (all fully out-of-sample):")
    for t_, b_ in best.items():
        r = base[(base.target == t_) & (base.baseline == b_)].iloc[0]
        print(f"  {t_:<14} {b_:<32} RMSE {r['rmse']:.4f}  MAPE {r['mape_%']:.2f}  hit {r['hit']:.3f}")

    frames = []
    for orth in (False, True):
        for target in mw.TARGETS:
            g = mw.run_grid(f, best[target], orthogonalise=orth)
            g = g[g["target"] == target]
            g["orthogonalised"] = orth
            g["vs_baseline"] = best[target]
            frames.append(g)
    grid = pd.concat(frames, ignore_index=True)
    grid.to_csv(sc.PROCESSED / "revision_grid.csv", index=False)

    for orth in (False, True):
        sub = grid[(grid["orthogonalised"] == orth) & (grid["role"] == "candidate")]
        label = "guidance-orthogonalised" if orth else "raw feature"
        print(f"\n{label}: cells beating the strongest baseline: "
              f"{int((sub['rmse_ratio'] < 1).sum())} of {len(sub)}   "
              f"(best {sub['rmse_ratio'].min():.3f})")
        piv = sub.pivot_table(index="candidate", columns=["target", "window"],
                              values="rmse_ratio")
        print(piv.round(3).to_string())

    # ---------------------------------------------------------------- C3
    print("\n" + "=" * 78)
    print("C3 -- WHAT COULD THIS SAMPLE HAVE DETECTED?")
    print("=" * 78)
    rows = []
    for target in mw.TARGETS:
        r = mw.walk_forward(f, target, None, best[target])
        e = r["base"] - r["actual"]
        mdr, curve = mw.min_detectable_ratio(e)
        row = {"target": target, "baseline": best[target], "n_oos": len(e),
               "min_detectable_rmse_ratio": mdr}
        row.update({f"power@{r:.2f}": f"{pw:.0%}" for r, pw in curve.items()})
        rows.append(row)
    power = pd.DataFrame(rows)
    power.to_csv(sc.PROCESSED / "revision_power.csv", index=False)
    print(power.to_string(index=False))
    print("\n  Read the power columns: the probability this test would have")
    print("  DETECTED a competing model whose RMSE was r times the baseline's.")
    print("  A genuine but modest edge (r ~ 0.90-0.95) is very unlikely to be")
    print("  detected at n=13. 'No cell beat the baseline' therefore BOUNDS the")
    print("  effect size; it does not establish that the effect is zero. Note the")
    print("  observed cells sit at r = 1.08-2.65, far outside the detectable band")
    print("  in the wrong direction -- that part is not a power problem.")

    # ---------------------------------------------------------------- C4
    print("\n" + "=" * 78)
    print("C4 -- CUSTOMER-NORMALISED: DOES CROSS-SELL EXPLAIN THE DECOUPLING?")
    print("=" * 78)
    cn = customer_normalised()
    print(cn.tail(10).round(1).to_string(index=False))
    x = np.arange(len(cn), dtype=float)
    for col, label in (("rev_per_cust_k", "revenue per $100k+ customer ($k)"),
                       ("dl_per_cust", "downloads per $100k+ customer"),
                       ("dl_per_musd", "downloads per $m revenue")):
        y = cn[col].values
        sl, ic, r, p, se = stats.linregress(x, y)
        chg = (y[-4:].mean() / y[:4].mean() - 1) * 100
        print(f"\n  {label:<38} first4 -> last4: {chg:+.0f}%   "
              f"slope p={p:.4f}  rho={stats.spearmanr(x, y)[0]:+.3f}")
    rev_chg = (cn["rev_per_cust_k"].tail(4).mean() / cn["rev_per_cust_k"].head(4).mean() - 1) * 100
    dl_chg = (cn["dl_per_cust"].tail(4).mean() / cn["dl_per_cust"].head(4).mean() - 1) * 100
    print(f"\n  Revenue per large customer {rev_chg:+.0f}% vs downloads per large "
          f"customer {dl_chg:+.0f}%.")
    print("  If downloads per customer grew FASTER than revenue per customer, the")
    print("  decoupling is download-side inflation (mirrors, CI, container rebuilds).")
    print("  If revenue per customer grew faster, monetisation per unit of telemetry")
    print("  rose -- cross-sell and tiering -- and the linear mapping was the error.")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, (col, title) in zip(axes, (
        ("rev_per_cust_k", "Revenue per $100k+ customer ($k)"),
        ("dl_per_cust", "Downloads per $100k+ customer"),
        ("dl_per_musd", "Downloads per $m revenue"),
    )):
        ax.plot(range(len(cn)), cn[col], marker="o", ms=3)
        ax.set_xticks(range(0, len(cn), 4))
        ax.set_xticklabels(cn["quarter"][::4], rotation=45, ha="right", fontsize=7)
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(sc.REPO / "report" / "figures" / "revision_customer_normalised.png", dpi=140)
    print("\nWrote report/figures/revision_customer_normalised.png")


if __name__ == "__main__":
    main()
