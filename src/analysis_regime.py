"""Structural break analysis (brief section 5.5), in the form that actually
matters for the live call.

The generic version of this question is "did revenue growth accelerate in
2026?" -- which the SEC data already answered (24.6% in 2025Q1 to 35.6% in
2026Q2). The version that changes a decision is narrower:

    **Is `beat_vs_guide` stationary?**

The headline nowcast is guidance midpoint x (1 + trailing 8-quarter mean beat).
That rule assumes the beat distribution is stable. If the beat is widening, the
trailing mean systematically under-predicts; if it is narrowing, it
over-predicts. So the stationarity of the beat, not of revenue growth, is what
the +/-$15m interval is conditional on.

Three tests:
  1. Trend in the beat series, full sample and recent sub-samples.
  2. A break comparison: last 4 quarters against the prior 4, with a bootstrap
     interval on the difference rather than an asymptotic p-value at n=4.
  3. Walk-forward residuals of the headline baseline, by quarter, checking
     whether they turn systematically signed from 2025 onward -- the specific
     diagnostic the brief asks for.

Outputs:
  processed/regime_beat_analysis.csv
  report/figures/regime_break.png
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import adfuller, kpss

import model_walkforward as mw
import sec_common as sc

SEED = 20260814
LIVE_GUIDE_MID = 1140.0  # 2026Q3, verified against 8-K 0001628280-26-053829


def trend_test(y: np.ndarray, label: str) -> dict:
    x = np.arange(len(y), dtype=float)
    slope, intercept, r, p, se = stats.linregress(x, y)
    rho, prho = stats.spearmanr(x, y)
    return {
        "window": label,
        "n": len(y),
        "mean_%": y.mean() * 100,
        "sd_pp": y.std(ddof=1) * 100,
        "slope_pp_per_qtr": slope * 100,
        "slope_p": p,
        "spearman_rho": rho,
        "spearman_p": prho,
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 220)

    f = mw.frame()
    b = f.dropna(subset=["beat_vs_guide"])[["quarter", "beat_vs_guide", "rev_yoy"]]
    b = b.reset_index(drop=True)
    y = b["beat_vs_guide"].values

    # ---------------- 1. trend ----------------
    print("=" * 78)
    print("IS beat_vs_guide STATIONARY?  (the assumption behind the live call)")
    print("=" * 78)
    rows = [
        trend_test(y, "full sample"),
        trend_test(y[-16:], "last 16 quarters"),
        trend_test(y[-12:], "last 12 quarters"),
        trend_test(y[-8:], "last 8 quarters (the rule's window)"),
    ]
    tt = pd.DataFrame(rows)
    print(tt.round(4).to_string(index=False))

    print("\nUnit-root / stationarity tests on the beat series:")
    for label, series in (("full sample", y), ("last 16", y[-16:])):
        adf_p = adfuller(series, autolag="AIC")[1]
        kpss_p = kpss(series, regression="c", nlags="auto")[1]
        verdict = (
            "stationary" if adf_p < 0.05 and kpss_p > 0.05
            else "non-stationary" if adf_p > 0.05 and kpss_p < 0.05
            else "inconclusive (tests disagree)"
        )
        print(f"  {label:<12} ADF p={adf_p:.3f}   KPSS p={kpss_p:.3f}   -> {verdict}")

    # ---------------- 2. recent break ----------------
    print("\n" + "=" * 78)
    print("LAST 4 QUARTERS vs PRIOR 4")
    print("=" * 78)
    last4, prior4 = y[-4:], y[-8:-4]
    diff = last4.mean() - prior4.mean()
    boot = [
        rng.choice(last4, 4, replace=True).mean() - rng.choice(prior4, 4, replace=True).mean()
        for _ in range(10000)
    ]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"  prior 4 ({b['quarter'].iloc[-8]}..{b['quarter'].iloc[-5]}): "
          f"mean {prior4.mean() * 100:.2f}%  sd {prior4.std(ddof=1) * 100:.2f}pp")
    print(f"  last  4 ({b['quarter'].iloc[-4]}..{b['quarter'].iloc[-1]}): "
          f"mean {last4.mean() * 100:.2f}%  sd {last4.std(ddof=1) * 100:.2f}pp")
    print(f"  difference {diff * 100:+.2f}pp   bootstrap 95% CI "
          f"[{lo * 100:+.2f}, {hi * 100:+.2f}]pp   "
          f"{'covers zero' if lo <= 0 <= hi else 'EXCLUDES zero'}")

    # ---------------- 3. walk-forward residuals ----------------
    print("\n" + "=" * 78)
    print("WALK-FORWARD RESIDUALS OF THE HEADLINE RULE, BY QUARTER")
    print("=" * 78)
    r = mw.walk_forward(f, "rev_yoy", None, "guidance + trailing beat (8q)")
    resid = pd.DataFrame(
        {
            "quarter": r["quarters"],
            "actual_%": r["actual"] * 100,
            "pred_%": r["base"] * 100,
            "residual_pp": (r["actual"] - r["base"]) * 100,
        }
    )
    print(resid.round(3).to_string(index=False))

    post = resid[resid["quarter"] >= "2025Q1"]["residual_pp"].values
    pre = resid[resid["quarter"] < "2025Q1"]["residual_pp"].values
    print(f"\n  pre-2025  (n={len(pre)}): mean {pre.mean():+.3f}pp, "
          f"{int((pre > 0).sum())}/{len(pre)} positive")
    print(f"  2025 on   (n={len(post)}): mean {post.mean():+.3f}pp, "
          f"{int((post > 0).sum())}/{len(post)} positive")
    if len(post) >= 3:
        sign_p = stats.binomtest(int((post > 0).sum()), len(post), 0.5).pvalue
        print(f"  sign test on the post-2025 residuals: p={sign_p:.3f} "
              f"(n={len(post)} -- underpowered, descriptive only)")

    # ---------------- 4. what it means for the live interval ----------------
    print("\n" + "=" * 78)
    print("CONSEQUENCE FOR THE 2026Q3 CALL")
    print("=" * 78)
    m8, s8 = y[-8:].mean(), y[-8:].std(ddof=1)
    flat = LIVE_GUIDE_MID * (1 + m8)
    # Trend-extrapolated alternative: fit the last 8 beats on time, project one
    # quarter ahead. Reported as a sensitivity, not as the headline.
    x8 = np.arange(8, dtype=float)
    sl, ic, *_ = stats.linregress(x8, y[-8:])
    trend_beat = ic + sl * 8
    trended = LIVE_GUIDE_MID * (1 + trend_beat)
    print(f"  guidance midpoint                     ${LIVE_GUIDE_MID:,.0f}m")
    print(f"  flat trailing-8 mean beat {m8 * 100:+.2f}%      -> ${flat:,.0f}m   "
          f"95% band [${LIVE_GUIDE_MID * (1 + m8 - 1.96 * s8):,.0f}m, "
          f"${LIVE_GUIDE_MID * (1 + m8 + 1.96 * s8):,.0f}m]")
    print(f"  trend-extrapolated beat   {trend_beat * 100:+.2f}%      -> ${trended:,.0f}m   "
          f"(sensitivity, not the headline)")
    print(f"  spread between the two treatments: ${abs(trended - flat):,.0f}m")
    print(f"  empirical min/max of last 8 beats applied: "
          f"[${LIVE_GUIDE_MID * (1 + y[-8:].min()):,.0f}m, "
          f"${LIVE_GUIDE_MID * (1 + y[-8:].max()):,.0f}m]")

    out = tt.copy()
    out.to_csv(sc.PROCESSED / "regime_beat_analysis.csv", index=False)
    resid.to_csv(sc.PROCESSED / "regime_walkforward_residuals.csv", index=False)

    # ---------------- figure ----------------
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    qi = np.arange(len(b))
    axes[0].plot(qi, b["beat_vs_guide"] * 100, marker="o", ms=3)
    axes[0].axhline(y[-8:].mean() * 100, ls="--", lw=1,
                    label=f"trailing-8 mean {y[-8:].mean() * 100:.2f}%")
    axes[0].set_xticks(qi[::4])
    axes[0].set_xticklabels(b["quarter"][::4], rotation=45, ha="right", fontsize=7)
    axes[0].set_title("beat vs guidance midpoint, %")
    axes[0].legend(fontsize=8)

    axes[1].plot(qi, b["rev_yoy"] * 100, marker="o", ms=3, color="tab:orange")
    axes[1].set_xticks(qi[::4])
    axes[1].set_xticklabels(b["quarter"][::4], rotation=45, ha="right", fontsize=7)
    axes[1].set_title("revenue YoY %, the 2026 acceleration")

    ri = np.arange(len(resid))
    colors = ["tab:red" if v < 0 else "tab:blue" for v in resid["residual_pp"]]
    axes[2].bar(ri, resid["residual_pp"], color=colors)
    axes[2].axhline(0, lw=0.5, color="grey")
    axes[2].set_xticks(ri)
    axes[2].set_xticklabels(resid["quarter"], rotation=45, ha="right", fontsize=7)
    axes[2].set_title("walk-forward residuals, headline rule (pp)")
    fig.tight_layout()
    fig.savefig(sc.REPO / "report" / "figures" / "regime_break.png", dpi=140)
    print("\nWrote report/figures/regime_break.png")


if __name__ == "__main__":
    main()
