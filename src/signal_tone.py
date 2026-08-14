"""Level 2 signal, the one variant that is actually backfillable: management
tone in the earnings press release.

The proposal for "Level 2" data lists three routes -- vendor blog previews via
Wayback, sell-side consensus revisions, and earnings-call transcripts. Two of
them have the same defect this project already diagnosed in Signal 1: the
freely available version is not reliably backfillable with correct vintages.
Vendor blogs are captured sporadically by the Internet Archive and are written
only when the vendor's data looks interesting; transcripts are vendor-licensed.

This one is different. The 8-K Exhibit 99.1 press release is:
  * free and official,
  * already cached here for all 28 quarters,
  * timestamped exactly -- it IS the guidance-issuance moment,
so a tone feature built from it has a perfect as-of vintage by construction.

**Hypothesis (sandbagging).** Guidance for Q(t) is issued in the Q(t-1) press
release. If management hedges more heavily when issuing that guidance, they may
be setting a lower bar, and the subsequent beat should be larger.

**Matched placebo, and this is the point of the design.** Every one of these
releases contains a templated forward-looking-statements disclaimer written by
counsel, not by management. Tone measured on THAT section should predict
nothing. If it predicts as well as the management-authored section, the tone
signal is measuring document length or boilerplate drift, not management.

The lexicon is a compact hand-specified list, not the full Loughran-McDonald
dictionary, and results are reported with that caveat.

Outputs:
  processed/tone_features.csv
  processed/tone_walkforward.csv
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

import model_walkforward as mw
import sec_common as sc

HEDGE = [
    "believe", "believes", "may", "could", "might", "approximately", "estimate",
    "estimates", "anticipate", "anticipates", "intend", "intends", "plan",
    "potential", "assume", "assumes", "subject to", "depend", "uncertain",
]
POSITIVE = [
    "strong", "strength", "record", "growth", "accelerate", "accelerated",
    "momentum", "robust", "expand", "expanded", "pleased", "excellent",
    "outperform", "confident",
]
NEGATIVE = [
    "decline", "declined", "weak", "weakness", "headwind", "slow", "slowed",
    "slowing", "challenge", "challenging", "pressure", "uncertainty", "risk",
    "difficult", "moderate", "moderated",
]

# The counsel-authored boilerplate. Everything from this heading onward is the
# placebo section; everything before it is the management-authored body.
DISCLAIMER_ANCHOR = re.compile(
    r"forward[- ]looking statements", re.IGNORECASE
)


def count_terms(text: str, terms: list[str]) -> int:
    low = text.lower()
    return sum(len(re.findall(rf"\b{re.escape(t)}\b", low)) for t in terms)


def split_sections(text: str) -> tuple[str, str]:
    """(management-authored body, counsel-authored disclaimer)."""
    m = DISCLAIMER_ANCHOR.search(text)
    if not m:
        return text, ""
    return text[: m.start()], text[m.start():]


def tone_features() -> pd.DataFrame:
    q = pd.read_csv(sc.PROCESSED / "ddog_quarters.csv")
    q = q[q["known_from_reliable"]].dropna(subset=["earnings_accn"])
    rows = []
    for _, r in q.iterrows():
        cache = sc.RAW / f"8k_ex99_{r['earnings_accn']}.txt"
        if not cache.exists():
            continue
        text = cache.read_text()
        body, disc = split_sections(text)
        wb, wd = max(len(body.split()), 1), max(len(disc.split()), 1)
        rows.append({
            # The quarter whose results this release REPORTS ...
            "reported_quarter": r["quarter"],
            "issued_on": r["earnings_date"],
            "body_words": wb,
            "hedge_rate": count_terms(body, HEDGE) / wb * 1000,
            "pos_rate": count_terms(body, POSITIVE) / wb * 1000,
            "neg_rate": count_terms(body, NEGATIVE) / wb * 1000,
            # placebo: same measures on counsel's boilerplate
            "plc_hedge_rate": count_terms(disc, HEDGE) / wd * 1000,
            "plc_pos_rate": count_terms(disc, POSITIVE) / wd * 1000,
            "plc_neg_rate": count_terms(disc, NEGATIVE) / wd * 1000,
        })
    df = pd.DataFrame(rows)
    df["net_tone"] = df["pos_rate"] - df["neg_rate"]
    df["plc_net_tone"] = df["plc_pos_rate"] - df["plc_neg_rate"]
    # ... and the guidance in that release applies to the NEXT quarter, so the
    # feature for quarter t comes from the release reporting t-1.
    df["quarter"] = (pd.PeriodIndex(df["reported_quarter"], freq="Q") + 1).astype(str)
    return df


def main() -> None:
    pd.set_option("display.width", 220)
    tone = tone_features()
    tone.to_csv(sc.PROCESSED / "tone_features.csv", index=False)

    print("=" * 78)
    print("MANAGEMENT TONE FROM THE 8-K PRESS RELEASE")
    print("=" * 78)
    print(f"{len(tone)} quarters, every one timestamped at the guidance-issuance "
          f"moment by construction.\n")
    print(tone[["quarter", "issued_on", "body_words", "hedge_rate", "net_tone",
                "plc_hedge_rate", "plc_net_tone"]].tail(8).round(2).to_string(index=False))

    f = mw.frame().merge(
        tone[["quarter", "hedge_rate", "net_tone", "plc_hedge_rate", "plc_net_tone"]],
        on="quarter", how="left",
    )

    # Descriptive: does hedging correlate with the subsequent beat at all?
    d = f.dropna(subset=["hedge_rate", "beat_vs_guide"])
    from scipy import stats as st
    print("\nCorrelation with the subsequent beat (descriptive, n=%d):" % len(d))
    for col in ("hedge_rate", "net_tone", "plc_hedge_rate", "plc_net_tone"):
        r, p = st.pearsonr(d[col], d["beat_vs_guide"])
        tag = "PLACEBO" if col.startswith("plc") else "signal "
        print(f"  {tag} {col:<16} r={r:+.3f}  p={p:.3f}")

    # Same walk-forward pipeline as every other signal.
    print("\n" + "=" * 78)
    print("IDENTICAL PIPELINE: walk-forward vs the strongest baseline")
    print("=" * 78)
    base = pd.read_csv(sc.PROCESSED / "wf_baselines.csv")
    best = base.sort_values("rmse").groupby("target").first()["baseline"].to_dict()
    rows = []
    for target in mw.TARGETS:
        for role, feat in (("signal", "hedge_rate"), ("signal", "net_tone"),
                           ("placebo", "plc_hedge_rate"), ("placebo", "plc_net_tone")):
            for b in dict.fromkeys(["AR(1)", best[target]]):
                r = mw.walk_forward(f, target, feat, b)
                if r is None:
                    continue
                e1, e2 = r["model"] - r["actual"], r["base"] - r["actual"]
                dm, p = mw.diebold_mariano(e1, e2)
                lo, hi = mw.bootstrap_rmse_ratio(e1, e2, np.random.default_rng(mw.SEED))
                m = mw.metrics(r["model"], r["actual"], r["prev"])
                mb = mw.metrics(r["base"], r["actual"], r["prev"])
                rows.append({
                    "target": target, "feature": feat, "role": role, "vs_baseline": b,
                    "n_oos": len(e1), "rmse_ratio": m["rmse"] / mb["rmse"],
                    "boot_lo": lo, "boot_hi": hi, "ci_covers_1": lo <= 1 <= hi,
                    "dm_p": p, "hit": m["hit"],
                })
    out = pd.DataFrame(rows)
    out.to_csv(sc.PROCESSED / "tone_walkforward.csv", index=False)
    print(out.round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for target in mw.TARGETS:
        sub = out[(out["target"] == target) & (out["vs_baseline"] == best[target])]
        sig = sub[sub["role"] == "signal"]
        plc = sub[sub["role"] == "placebo"]
        if sig.empty:
            continue
        print(f"\ntarget = {target}  vs {best[target]}")
        print(f"  best management-tone cell: {sig['rmse_ratio'].min():.3f}")
        print(f"  best boilerplate placebo:  {plc['rmse_ratio'].min():.3f}")
        beat = int((sig["rmse_ratio"] < 1).sum())
        print(f"  signal cells beating the baseline: {beat} of {len(sig)}")


if __name__ == "__main__":
    main()
