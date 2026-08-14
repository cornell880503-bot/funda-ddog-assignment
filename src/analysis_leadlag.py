"""Phase 3 -- lead-lag analysis.

Two different questions get conflated under the word "leads", and this module
keeps them apart:

  (A) CROSS-QUARTER LEAD. Does quarter t-1's download growth predict quarter
      t's revenue growth? This is what a cross-correlation function measures.
      It is the weaker question: by the time quarter t-1's downloads are known,
      most of quarter t-1's revenue is knowable too.

  (B) WITHIN-QUARTER LEAD -- the operational one. Does the first 45 days of
      quarter t's downloads predict quarter t's revenue, at a moment when the
      quarter is still open and the print is ~83 days away? This is the only
      version of "leads" that is actionable, and it is where the time goes.

Every test carries its negative control through the identical path:
  dd_rel_plc -> ctrl_rel_plc,  dd_rel -> plc_rel,  dd_abs -> plc_abs.
A result that the control also produces is not a result.

Granger causality is reported as DESCRIPTIVE ONLY. With n around 24 quarters
these tests have almost no power and their p-values should not be read as
evidence of anything.

Outputs:
  processed/leadlag_stationarity.csv
  processed/leadlag_ccf.csv
  processed/leadlag_partial_quarter.csv
  report/figures/leadlag_ccf.png
  report/figures/partial_quarter.png
"""

from __future__ import annotations

import contextlib
import io
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, grangercausalitytests, kpss

import build_panel
import sec_common as sc

warnings.filterwarnings("ignore")

CANDIDATES = ["dd_rel_plc", "dd_rel", "dd_abs"]  # a priori ranked, LOG D24
CONTROLS = {"dd_rel_plc": "ctrl_rel_plc", "dd_rel": "plc_rel", "dd_abs": "plc_abs"}
TARGETS = ["rev_yoy", "beat_vs_guide"]
FIRST_TRAIN = 12  # quarters in the initial training window
SEED = 20260814


def build_analysis_frame() -> pd.DataFrame:
    """Targets plus features at every horizon, one row per quarter.

    Horizon columns are kept side by side deliberately: the whole point is to
    compare what was knowable at day 30/45/60 against the full quarter.
    """
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    g = pd.read_csv(sc.MANUAL / "guidance_template.csv").rename(
        columns={"guided_quarter": "quarter"}
    )
    g["guide_mid"] = (g["guide_low_musd"] + g["guide_high_musd"]) / 2
    df = q.merge(g[["quarter", "guide_mid"]], on="quarter", how="left")
    df["beat_vs_guide"] = df["revenue_musd"] / df["guide_mid"] - 1
    df = df[df["known_from_reliable"]][
        ["quarter", "revenue_musd", "rev_yoy", "beat_vs_guide", "guide_mid"]
    ]

    v = build_panel.load_vintages()
    wide = v.pivot_table(index="quarter", columns="feature", values="value")
    out = df.merge(wide, left_on="quarter", right_index=True, how="left")
    out = out.sort_values("quarter").reset_index(drop=True)
    # rev_yoy_lag1 is the AR(1) baseline's information set.
    out["rev_yoy_lag1"] = out["rev_yoy"].shift(1)
    return out


# ------------------------------------------------------------- stationarity


def stationarity(frame: pd.DataFrame) -> pd.DataFrame:
    cols = TARGETS + [f"{c}_full" for c in CANDIDATES] + [
        f"{v}_full" for v in CONTROLS.values()
    ]
    rows = []
    for col in cols:
        s = frame[col].dropna()
        if len(s) < 12:
            continue
        adf_p = adfuller(s, autolag="AIC")[1]
        kpss_p = kpss(s, regression="c", nlags="auto")[1]
        # ADF null = unit root; KPSS null = stationary. Agreement is what counts.
        if adf_p < 0.05 and kpss_p > 0.05:
            verdict = "stationary (both agree)"
        elif adf_p > 0.05 and kpss_p < 0.05:
            verdict = "non-stationary (both agree)"
        else:
            verdict = "inconclusive (tests disagree)"
        rows.append(
            {"series": col, "n": len(s), "adf_p": adf_p, "kpss_p": kpss_p,
             "verdict": verdict}
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------- cross-quarter CCF


def ccf_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Correlation of feature at t+lag with target at t, lags -2..+2.

    lag < 0 means the feature leads the target.
    """
    rows = []
    feats = [f"{c}_full" for c in CANDIDATES] + [f"{v}_full" for v in CONTROLS.values()]
    for target in TARGETS:
        for feat in feats:
            for lag in range(-2, 3):
                x = frame[feat].shift(-lag)
                joint = pd.concat([x, frame[target]], axis=1).dropna()
                if len(joint) < 8:
                    continue
                rows.append(
                    {
                        "target": target,
                        "feature": feat,
                        "lag_quarters": lag,
                        "corr": joint.iloc[:, 0].corr(joint.iloc[:, 1]),
                        "n": len(joint),
                        "is_control": feat.startswith(("plc_", "ctrl_")),
                    }
                )
    return pd.DataFrame(rows)


def granger_descriptive(frame: pd.DataFrame) -> pd.DataFrame:
    """Granger tests. DESCRIPTIVE ONLY -- n is far too small to conclude."""
    rows = []
    for target in TARGETS:
        for cand in CANDIDATES + list(CONTROLS.values()):
            col = f"{cand}_full"
            data = frame[[target, col]].dropna()
            if len(data) < 14:
                continue
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    res = grangercausalitytests(data, maxlag=2)
                for lag, r in res.items():
                    rows.append(
                        {
                            "target": target,
                            "feature": col,
                            "lag": lag,
                            "p_value": r[0]["ssr_ftest"][1],
                            "n": len(data),
                            "is_control": cand in CONTROLS.values(),
                        }
                    )
            except Exception:
                continue
    return pd.DataFrame(rows)


# ------------------------------------------------- the within-quarter test


def partial_corr(x: pd.Series, y: pd.Series, z: pd.Series) -> tuple[float, int]:
    """corr(x, y) after removing what z explains of each."""
    d = pd.concat([x, y, z], axis=1).dropna()
    if len(d) < 8:
        return np.nan, len(d)
    Z = np.column_stack([np.ones(len(d)), d.iloc[:, 2].values])
    rx = d.iloc[:, 0].values - Z @ np.linalg.lstsq(Z, d.iloc[:, 0].values, rcond=None)[0]
    ry = d.iloc[:, 1].values - Z @ np.linalg.lstsq(Z, d.iloc[:, 1].values, rcond=None)[0]
    return float(np.corrcoef(rx, ry)[0, 1]), len(d)


def walk_forward(frame: pd.DataFrame, feature: str, target: str) -> dict:
    """Expanding-window OOS test of one feature against the AR(1) baseline.

    Train on the first FIRST_TRAIN quarters, predict the next, refit, repeat.
    The baseline is the same procedure using only rev_yoy_lag1, which is what
    an analyst knows for free.
    """
    d = frame[["quarter", target, feature, "rev_yoy_lag1"]].dropna().reset_index(drop=True)
    if len(d) < FIRST_TRAIN + 4:
        return {}
    preds, base_preds, actual, quarters = [], [], [], []
    for i in range(FIRST_TRAIN, len(d)):
        tr, te = d.iloc[:i], d.iloc[i]
        for cols, store in (
            ([feature, "rev_yoy_lag1"], preds),
            (["rev_yoy_lag1"], base_preds),
        ):
            X = np.column_stack([np.ones(len(tr))] + [tr[c].values for c in cols])
            beta = np.linalg.lstsq(X, tr[target].values, rcond=None)[0]
            store.append(float(np.dot([1.0] + [te[c] for c in cols], beta)))
        actual.append(te[target])
        quarters.append(te["quarter"])

    a, p, b = np.array(actual), np.array(preds), np.array(base_preds)
    prev = d[target].shift(1).iloc[FIRST_TRAIN:].values

    def metrics(pred):
        err = pred - a
        return {
            "rmse": float(np.sqrt(np.mean(err**2))),
            "mae": float(np.mean(np.abs(err))),
            "hit": float(np.mean(np.sign(pred - prev) == np.sign(a - prev))),
        }

    m, mb = metrics(p), metrics(b)
    return {
        "feature": feature,
        "target": target,
        "n_oos": len(a),
        "rmse": m["rmse"],
        "rmse_ar1": mb["rmse"],
        "rmse_ratio": m["rmse"] / mb["rmse"],
        "mae": m["mae"],
        "mae_ar1": mb["mae"],
        "hit": m["hit"],
        "hit_ar1": mb["hit"],
        "beats_ar1": m["rmse"] < mb["rmse"],
    }


def partial_quarter_analysis(frame: pd.DataFrame) -> pd.DataFrame:
    """The core Phase 3 result: does day-45 information predict the quarter?"""
    rows = []
    for target in TARGETS:
        for cand in CANDIDATES:
            ctrl = CONTROLS[cand]
            for tag in ("d30", "d45", "d60", "full"):
                feat = f"{cand}_{tag}"
                cfeat = f"{ctrl}_{tag}"
                if feat not in frame:
                    continue
                raw = frame[[feat, target]].dropna()
                pc, n = partial_corr(frame[feat], frame[target], frame["rev_yoy_lag1"])
                pc_ctrl, _ = partial_corr(frame[cfeat], frame[target], frame["rev_yoy_lag1"])
                wf = walk_forward(frame, feat, target)
                wf_ctrl = walk_forward(frame, cfeat, target)
                rows.append(
                    {
                        "target": target,
                        "candidate": cand,
                        "horizon": tag,
                        "n": len(raw),
                        "corr": raw[feat].corr(raw[target]),
                        "partial_corr_given_ar1": pc,
                        "control_partial_corr": pc_ctrl,
                        "oos_rmse_ratio_vs_ar1": wf.get("rmse_ratio", np.nan),
                        "control_rmse_ratio": wf_ctrl.get("rmse_ratio", np.nan),
                        "oos_hit": wf.get("hit", np.nan),
                        "ar1_hit": wf.get("hit_ar1", np.nan),
                        "n_oos": wf.get("n_oos", np.nan),
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    np.random.seed(SEED)
    frame = build_analysis_frame()
    frame.to_csv(sc.PROCESSED / "analysis_frame.csv", index=False)
    pd.set_option("display.width", 230)

    n_full = frame[f"{CANDIDATES[0]}_full"].notna().sum()
    print(f"Analysis sample: {len(frame)} quarters, "
          f"{n_full} with full-quarter features "
          f"({frame['quarter'].iloc[0]} .. {frame['quarter'].iloc[-1]})\n")

    print("=" * 76)
    print("STATIONARITY (ADF null = unit root; KPSS null = stationary)")
    print("=" * 76)
    st = stationarity(frame)
    st.to_csv(sc.PROCESSED / "leadlag_stationarity.csv", index=False)
    print(st.round(4).to_string(index=False))

    print("\n" + "=" * 76)
    print("(A) CROSS-QUARTER CCF -- the weaker question")
    print("=" * 76)
    ccf = ccf_table(frame)
    ccf.to_csv(sc.PROCESSED / "leadlag_ccf.csv", index=False)
    for target in TARGETS:
        piv = (
            ccf[ccf["target"] == target]
            .pivot(index="feature", columns="lag_quarters", values="corr")
        )
        print(f"\ntarget = {target}   (lag < 0 means the feature LEADS)")
        print(piv.round(3).to_string())

    print("\n" + "=" * 76)
    print("GRANGER -- DESCRIPTIVE ONLY, n is far too small to conclude")
    print("=" * 76)
    gr = granger_descriptive(frame)
    if len(gr):
        print(gr.pivot_table(index=["target", "feature"], columns="lag",
                             values="p_value").round(3).to_string())
    print("\nDo not read these as evidence. With n around 24 and two lags, the"
          "\ntests have almost no power, and a p-value below 0.05 here is as"
          "\nlikely to be noise as signal. Reported because the brief asks for"
          "\nthem, and labelled as descriptive.")

    print("\n" + "=" * 76)
    print("(B) WITHIN-QUARTER TEST -- the operational question")
    print("=" * 76)
    pq = partial_quarter_analysis(frame)
    pq.to_csv(sc.PROCESSED / "leadlag_partial_quarter.csv", index=False)
    for target in TARGETS:
        print(f"\ntarget = {target}")
        print(pq[pq["target"] == target].drop(columns=["target"]).round(3).to_string(index=False))

    # ---- verdict, stated against the pre-registered ranking ----
    print("\n" + "=" * 76)
    print("VERDICT vs the a priori ranking fixed in LOG D24")
    print("=" * 76)
    from scipy import stats as _st

    for target in TARGETS:
        print(f"\ntarget = {target}")
        sub = pq[(pq["target"] == target) & (pq["horizon"] == "d45")]
        for rank, cand in enumerate(CANDIDATES, start=1):
            r = sub[sub["candidate"] == cand]
            if r.empty:
                continue
            r = r.iloc[0]
            beats = r["oos_rmse_ratio_vs_ar1"] < 1
            ctrl_beats = r["control_rmse_ratio"] < 1
            n_oos = int(r["n_oos"])
            hits = int(round(r["oos_hit"] * n_oos))
            p_hit = _st.binomtest(hits, n_oos, 0.5).pvalue
            if beats and not ctrl_beats:
                verdict = "beats AR(1); its control does NOT -> genuine edge"
            elif beats and ctrl_beats:
                verdict = "beats AR(1) but SO DOES ITS CONTROL -> not attributable to Datadog"
            elif ctrl_beats:
                verdict = "FAILS to beat AR(1) while its control does -> no support"
            else:
                verdict = "FAILS to beat AR(1)"
            print(
                f"  rank {rank}  {cand:<11} rmse_ratio={r['oos_rmse_ratio_vs_ar1']:.3f} "
                f"(control {r['control_rmse_ratio']:.3f})  "
                f"hit={hits}/{n_oos} p={p_hit:.2f}\n"
                f"            -> {verdict}"
            )
    print(
        "\nHit-rate p-values are two-sided binomial against 0.5. None of these"
        "\nsamples can distinguish skill from chance at n=13-14; a hit rate is"
        "\nreported only because the brief asks for it."
    )

    # ---- figures ----
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    for ax, target in zip(axes, TARGETS):
        sub = ccf[ccf["target"] == target]
        for feat, grp in sub.groupby("feature"):
            is_ctrl = grp["is_control"].iloc[0]
            ax.plot(grp["lag_quarters"], grp["corr"], marker="o", ms=4,
                    ls="--" if is_ctrl else "-", alpha=0.55 if is_ctrl else 1.0,
                    label=feat.replace("_full", ""))
        ax.axhline(0, lw=0.5, color="grey")
        ax.axvline(0, lw=0.5, color="grey")
        ax.set_title(f"CCF vs {target}  (dashed = negative control)", fontsize=10)
        ax.set_xlabel("lag (quarters); negative = feature leads")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(sc.REPO / "report" / "figures" / "leadlag_ccf.png", dpi=140)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    order = ["d30", "d45", "d60", "full"]
    for ax, target in zip(axes, TARGETS):
        sub = pq[pq["target"] == target]
        for cand, grp in sub.groupby("candidate"):
            grp = grp.set_index("horizon").loc[order]
            ax.plot(order, grp["partial_corr_given_ar1"], marker="o", label=cand)
            ax.plot(order, grp["control_partial_corr"], marker="x", ls=":",
                    alpha=0.6, label=f"{CONTROLS[cand]} (control)")
        ax.axhline(0, lw=0.5, color="grey")
        ax.set_title(f"Partial corr with {target}, given AR(1)", fontsize=10)
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(sc.REPO / "report" / "figures" / "partial_quarter.png", dpi=140)
    print("\nWrote report/figures/leadlag_ccf.png, partial_quarter.png")


if __name__ == "__main__":
    main()
