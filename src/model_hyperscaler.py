"""Signal 2 through the identical pipeline.

Same as-of construction, same expanding walk-forward, same baseline set, same
error metrics, same significance tests, own matched control. Nothing here is
bespoke -- it imports the Phase 4 machinery and swaps the feature.

As-of legality: every feature is dated by the peer's own Item 2.02 8-K, and
all three peers reported before Datadog in all 28 quarters (LOG D15, median
lead 7 days for Amazon). So a hyperscaler read for quarter t is legitimately
available before Datadog reports quarter t -- unlike the download features,
this signal's timing advantage is a matter of filing dates, not of estimation.

Coverage is uneven and is reported as such:
  azure_ic_yoy    28/28   Microsoft Intelligent Cloud
  amzn_total_yoy  28/28   control: Amazon total net sales (non-cloud mix)
  msft_pbp_yoy    28/28   control: Microsoft Productivity & Business Processes
  aws_yoy         16/28   older Amazon releases state AWS growth only in tables
  gcp_yoy          8/28   older Alphabet releases give levels, not growth rates

Outputs:
  processed/wf_hyperscaler.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import model_walkforward as mw
import sec_common as sc

# Signal / matched-control pairs. Controls come from the SAME filing where
# possible, so issuer, quarter, macro and extraction method are all held fixed.
PAIRS = [
    ("azure_ic_yoy", "msft_pbp_yoy"),  # same issuer, same release, non-cloud
    ("aws_yoy", "amzn_total_yoy"),  # same issuer, same release, whole company
]


def frame_with_hyperscaler() -> pd.DataFrame:
    f = mw.frame()
    h = pd.read_csv(sc.PROCESSED / "hyperscaler_segment_growth.csv")
    piv = h.pivot_table(index="quarter", columns="series", values="yoy")
    return f.merge(piv, left_on="quarter", right_index=True, how="left")


def main() -> None:
    f = frame_with_hyperscaler()
    pd.set_option("display.width", 240)

    cov = {c: int(f[c].notna().sum()) for _, pair in enumerate(PAIRS) for c in pair}
    print("Coverage (quarters with a value):", cov, "\n")

    print("=" * 78)
    print("SIGNAL 2 -- hyperscaler cloud growth, identical pipeline")
    print("=" * 78)

    base_tbl = pd.read_csv(sc.PROCESSED / "wf_baselines.csv")
    best = base_tbl.sort_values("rmse").groupby("target").first()["baseline"].to_dict()

    rows = []
    for target in mw.TARGETS:
        for signal, control in PAIRS:
            for role, feat in (("signal", signal), ("control", control)):
                for baseline in dict.fromkeys(["AR(1)", best[target]]):
                    r = mw.walk_forward(f, target, feat, baseline)
                    if r is None:
                        print(f"  skipped {feat} vs {baseline} ({target}): "
                              f"insufficient overlapping history")
                        continue
                    e1 = r["model"] - r["actual"]
                    e2 = r["base"] - r["actual"]
                    dm, p = mw.diebold_mariano(e1, e2)
                    lo, hi = mw.bootstrap_rmse_ratio(
                        e1, e2, np.random.default_rng(mw.SEED)
                    )
                    m = mw.metrics(r["model"], r["actual"], r["prev"])
                    mb = mw.metrics(r["base"], r["actual"], r["prev"])
                    rows.append(
                        {
                            "target": target,
                            "feature": feat,
                            "role": role,
                            "vs_baseline": baseline,
                            "n_oos": len(e1),
                            "rmse_ratio": m["rmse"] / mb["rmse"],
                            "boot_ci_lo": lo,
                            "boot_ci_hi": hi,
                            "ci_covers_1": lo <= 1 <= hi,
                            "dm_p": p,
                            "mape_%": m["mape_%"],
                            "hit": m["hit"],
                        }
                    )
    out = pd.DataFrame(rows)
    out.to_csv(sc.PROCESSED / "wf_hyperscaler.csv", index=False)
    print(out.round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for target in mw.TARGETS:
        opp = best[target]
        sub = out[(out["target"] == target) & (out["vs_baseline"] == opp)]
        if sub.empty:
            continue
        print(f"\ntarget = {target}, strongest baseline = {opp}")
        for _, r in sub.iterrows():
            verdict = (
                "beats it" if r["rmse_ratio"] < 1 else "loses to it"
            ) + (
                ", CI excludes 1.0" if not r["ci_covers_1"] else ", CI covers 1.0"
            )
            print(f"  {r['role']:<8} {r['feature']:<16} ratio={r['rmse_ratio']:.3f} "
                  f"CI=[{r['boot_ci_lo']:.3f}, {r['boot_ci_hi']:.3f}] "
                  f"DM p={r['dm_p']:.3f}  -> {verdict}")

    print(
        "\nSame decision rule as the download signals: a cell counts only if it"
        "\nbeats the STRONGEST baseline, its bootstrap CI excludes 1.0, and its"
        "\nmatched control fails. Beating AR(1) alone is not sufficient (D27)."
    )


if __name__ == "__main__":
    main()
