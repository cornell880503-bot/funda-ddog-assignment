"""Phase 2 checkpoint: the as-of panel at three sample dates.

Prints, for each sample as-of date, the features that were legally available
and -- more usefully for review -- the features that were WITHHELD and the date
each of them would have become available. The withheld list is the part worth
checking: it is where look-ahead bias would have entered.
"""

from __future__ import annotations

import pandas as pd

import build_panel
import sec_common as sc

SAMPLES = [
    # (quarter, as-of date, what this represents)
    ("2025Q4", "2025-11-15", "day 46 of the quarter -- mid-quarter, still actionable"),
    ("2026Q2", "2026-08-05", "the day before Datadog reported Q2 (8-K 2026-08-06)"),
    ("2026Q3", "2026-08-14", "today -- the live quarter, day 45"),
]


def main() -> None:
    vintages = build_panel.load_vintages()
    targets = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    pd.set_option("display.width", 200)

    for quarter, asof, note in SAMPLES:
        asof_d = pd.Timestamp(asof).date()
        allq = vintages[vintages["quarter"] == quarter]
        legal = allq[allq["available_from"] <= asof_d]
        withheld = allq[allq["available_from"] > asof_d]

        print("=" * 78)
        print(f"{quarter}  as of {asof}   ({note})")
        print("=" * 78)

        t = targets[targets["quarter"] == quarter]
        if len(t) and pd.notna(t["revenue_musd"].iloc[0]):
            reported = t["earnings_date"].iloc[0]
            print(f"Outcome (NOT visible at this as-of date): "
                  f"revenue ${t['revenue_musd'].iloc[0]:,.1f}m, "
                  f"YoY {t['rev_yoy'].iloc[0] * 100:.1f}%, reported {reported}")
        else:
            print("Outcome: not yet reported -- this is the live nowcast target")

        print(f"\nLEGAL at this date: {len(legal)} features")
        print(
            legal[["feature", "value", "available_from", "source"]]
            .sort_values("available_from")
            .to_string(index=False, float_format=lambda v: f"{v:,.4f}")
        )

        if len(withheld):
            print(f"\nWITHHELD: {len(withheld)} features not yet public")
            w = withheld[["feature", "available_from", "source"]].sort_values("available_from")
            w = w.assign(days_early=[(pd.Timestamp(d).date() - asof_d).days
                                     for d in w["available_from"]])
            print(w.to_string(index=False))
        else:
            print("\nWITHHELD: none")
        print()

    print("=" * 78)
    print("Live quarter under all three outage treatments")
    print("=" * 78)
    treat = build_panel.live_quarter_treatments()
    print(treat.round(4).to_string(index=False))
    spread_rel = treat["dd_rel_yoy_log"].max() - treat["dd_rel_yoy_log"].min()
    spread_abs = treat["dd_abs_yoy_log"].max() - treat["dd_abs_yoy_log"].min()
    print(
        f"\nTreatment spread: absolute feature {spread_abs:.4f} log points, "
        f"relative feature {spread_rel:.4f}."
    )
    print(
        "The relative feature is roughly an order of magnitude less sensitive to the\n"
        "outage treatment, because an API outage suppresses the Datadog and control\n"
        "baskets together and the difference cancels it. That is a second, independent\n"
        "argument for the relative construction, separate from the ecosystem-trend one."
    )


if __name__ == "__main__":
    main()
