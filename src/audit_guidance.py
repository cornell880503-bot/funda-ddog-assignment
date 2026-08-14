"""Audit the auto-extracted guidance table before any of it is trusted.

The extraction in fetch_guidance.py is a regex over press-release text. Regexes
misparse. This script does not re-read the filings; it applies four independent
consistency checks that a misparse is unlikely to survive, and produces a
review worklist so manual verification is spent on the rows that need it.

Checks
  A. range_width -- guidance range width as a share of the midpoint. Datadog
     guides a tight band; an unusually wide or zero-width range means the
     regex caught the wrong pair of numbers.
  B. below_midpoint -- actual revenue below the guided midpoint. Datadog has
     beaten its midpoint in every quarter on record, so a "miss" is far more
     likely to be a misparse than a real event. Flagged, never auto-corrected.
  C. midpoint_yoy_jump -- YoY growth implied by the midpoint should evolve
     smoothly. A discontinuity means a units error (billions read as millions)
     or a wrong quarter.
  D. issue_date_mismatch -- guidance for Q(t) is issued on the Q(t-1) earnings
     call, so issued_on must equal the prior quarter's earnings date in the SEC
     filing data. This is an external cross-check, not a self-consistency one.

Outputs:
  manual/guidance_audit.csv        every row, every check, with reasons
  manual/verification_worklist.csv rows requiring manual sign-off
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import sec_common as sc

# Thresholds. Set from the observed distribution, then stated explicitly rather
# than tuned until nothing flags.
WIDTH_MAX = 0.030  # range width / midpoint; DDOG's typical band is ~0.4-1.1%
YOY_JUMP_MAX = 0.10  # 10pp change in midpoint-implied YoY vs the prior quarter
RECENT_N = 8  # last N quarters always get manual sign-off


def main() -> None:
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    g = pd.read_csv(sc.MANUAL / "guidance_template.csv")

    q = q.rename(columns={"quarter": "guided_quarter"})
    df = g.merge(
        q[["guided_quarter", "revenue_musd", "earnings_date", "known_from_reliable"]],
        on="guided_quarter",
        how="left",
    )
    df["guide_mid"] = (df["guide_low_musd"] + df["guide_high_musd"]) / 2
    df["range_width_pct"] = (
        (df["guide_high_musd"] - df["guide_low_musd"]) / df["guide_mid"] * 100
    )
    df["beat_vs_guide_pct"] = (df["revenue_musd"] / df["guide_mid"] - 1) * 100

    # C: midpoint-implied YoY, and how much it moves quarter to quarter.
    per = pd.PeriodIndex(df["guided_quarter"], freq="Q")
    mid = pd.Series(df["guide_mid"].values, index=per).reindex(
        pd.period_range(per.min(), per.max(), freq="Q")
    )
    mid_yoy = (mid / mid.shift(4) - 1).reindex(per).values
    df["midpoint_yoy"] = mid_yoy
    df["midpoint_yoy_delta"] = pd.Series(mid_yoy).diff()

    # D: issued_on should be the earnings date of the quarter being reported.
    rep = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")[["quarter", "earnings_date"]]
    rep = rep.rename(
        columns={"quarter": "reported_quarter", "earnings_date": "sec_earnings_date"}
    )
    df = df.merge(rep, on="reported_quarter", how="left")

    df["flag_A_range_width"] = (df["range_width_pct"] / 100 > WIDTH_MAX) | (
        df["range_width_pct"] <= 0
    )
    df["flag_B_below_midpoint"] = df["beat_vs_guide_pct"] < 0
    df["flag_C_yoy_jump"] = df["midpoint_yoy_delta"].abs() > YOY_JUMP_MAX
    df["flag_D_date_mismatch"] = df["issued_on"] != df["sec_earnings_date"]
    df["flag_E_unparsed"] = df["guide_mid"].isna()

    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    df["n_flags"] = df[flag_cols].sum(axis=1)
    df["reasons"] = [
        "; ".join(c.replace("flag_", "") for c in flag_cols if row[c])
        for _, row in df.iterrows()
    ]

    per_idx = pd.PeriodIndex(df["guided_quarter"], freq="Q")
    df["is_recent"] = per_idx >= per_idx.max() - (RECENT_N - 1)
    df["needs_manual_check"] = df["is_recent"] | (df["n_flags"] > 0)
    df["verified"] = ""

    out_cols = [
        "guided_quarter",
        "reported_quarter",
        "issued_on",
        "sec_earnings_date",
        "guide_low_musd",
        "guide_high_musd",
        "guide_mid",
        "revenue_musd",
        "range_width_pct",
        "beat_vs_guide_pct",
        "midpoint_yoy",
        "midpoint_yoy_delta",
        "n_flags",
        "reasons",
        "needs_manual_check",
        "verified",
        "guide_sentence",
        "accession",
        "url",
    ]
    audit = df[out_cols]
    audit.to_csv(sc.MANUAL / "guidance_audit.csv", index=False)

    work = audit[audit["needs_manual_check"]].copy()
    work.to_csv(sc.MANUAL / "verification_worklist.csv", index=False)

    # ---- report ----
    pd.set_option("display.width", 200)
    print("Guidance audit\n" + "=" * 70)
    print(f"rows: {len(audit)}   flagged: {(audit['n_flags'] > 0).sum()}   "
          f"manual worklist: {len(work)}\n")

    print("Range width as % of midpoint:")
    print(audit["range_width_pct"].describe().round(3).to_string())
    print()
    print("Beat vs midpoint, %:")
    print(audit["beat_vs_guide_pct"].describe().round(3).to_string())
    print()

    for col in flag_cols:
        hits = audit[df[col].values]
        label = col.replace("flag_", "")
        if hits.empty:
            print(f"[pass] {label}: no rows")
        else:
            print(f"[FLAG] {label}: {len(hits)} row(s) -> "
                  f"{', '.join(hits['guided_quarter'])}")
    print()
    print("Worklist (manual sign-off required):")
    print(
        work[
            [
                "guided_quarter",
                "issued_on",
                "guide_low_musd",
                "guide_high_musd",
                "revenue_musd",
                "beat_vs_guide_pct",
                "reasons",
            ]
        ]
        .round(3)
        .to_string(index=False)
    )
    print(
        "\nProcedure: check each worklist row against its 8-K EX-99.1 (url column),"
        "\nset verified=yes, and DROP any row that cannot be confirmed from the"
        "\nprimary document. A shorter sample beats a wrong one."
    )
    print(f"\nWrote {(sc.MANUAL / 'guidance_audit.csv').relative_to(sc.REPO)}")
    print(f"Wrote {(sc.MANUAL / 'verification_worklist.csv').relative_to(sc.REPO)}")


if __name__ == "__main__":
    main()
