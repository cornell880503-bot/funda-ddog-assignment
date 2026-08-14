"""Verify the auto-extracted guidance against the primary documents.

This is deliberately NOT a re-run of `fetch_guidance.py`. Re-running the same
regex would only prove the regex is deterministic. The check here uses an
independent parsing path over the same cached 8-K exhibit text:

  original path : locate a sentence matching "revenue between ...", then pull
                  the first money-range match out of that sentence.
  check path    : locate the "Outlook" heading, take the following window,
                  enumerate EVERY dollar amount in it with its unit, and ask
                  whether the template's low and high both appear among them
                  in the right order and the right units.

Agreement between two different parsers over the same primary text is real
evidence. It is still not the same as a human reading the filing, and the
report says so: this script fills `machine_verified`, and the `verified`
column is reserved for human sign-off on the numbers that get spoken aloud.

Outputs:
  manual/guidance_verified.csv
  manual/verification_evidence.txt   verbatim windows, one per row, for eyeball
"""

from __future__ import annotations

import re

import pandas as pd

import sec_common as sc

MONEY = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)?", re.IGNORECASE
)
OUTLOOK = re.compile(r"(?:financial|business)?\s*outlook", re.IGNORECASE)
WINDOW_CHARS = 1600


def to_musd(value: str, unit: str | None, inherit: str | None = None) -> float | None:
    v = float(value.replace(",", ""))
    u = (unit or inherit or "").lower()
    if u == "billion":
        return round(v * 1000, 3)
    if u == "million":
        return v
    return None


def independent_parse(text: str, quarter: str) -> dict:
    """Enumerate every dollar amount in the outlook window, independently."""
    out = {"amounts_musd": [], "window": "", "anchor": None}
    # Anchor on the outlook heading for the specific guided quarter where
    # possible, otherwise the first outlook heading in the document.
    qnum = int(quarter[-1])
    ordinal = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}[qnum]
    specific = re.search(
        rf"{ordinal} Quarter\s+\d{{4}}\s+Outlook", text, re.IGNORECASE
    )
    anchor = specific or OUTLOOK.search(text)
    if not anchor:
        return out
    out["anchor"] = text[anchor.start() : anchor.end()]
    window = text[anchor.start() : anchor.start() + WINDOW_CHARS]
    out["window"] = window

    amounts = []
    matches = list(MONEY.finditer(window))
    for i, m in enumerate(matches):
        val, unit = m.group(1), m.group(2)
        # A range's first figure often carries no unit ("$1.07 billion and
        # $1.08 billion" does; "$951 and $961 million" does not). Inherit the
        # unit from the next amount when missing.
        inherit = matches[i + 1].group(2) if unit is None and i + 1 < len(matches) else None
        musd = to_musd(val, unit, inherit)
        if musd is not None:
            amounts.append(musd)
    out["amounts_musd"] = amounts
    return out


def main() -> None:
    work = pd.read_csv(sc.MANUAL / "verification_worklist.csv")
    audit = pd.read_csv(sc.MANUAL / "guidance_audit.csv")

    rows, evidence = [], []
    for _, r in audit.iterrows():
        accn = r["accession"]
        cache = sc.RAW / f"8k_ex99_{accn}.txt"
        if not cache.exists():
            rows.append({**r.to_dict(), "machine_verified": "no cached document"})
            continue
        text = cache.read_text()
        chk = independent_parse(text, r["guided_quarter"])
        lo, hi = r["guide_low_musd"], r["guide_high_musd"]
        found_lo = any(abs(a - lo) < 0.51 for a in chk["amounts_musd"])
        found_hi = any(abs(a - hi) < 0.51 for a in chk["amounts_musd"])
        # Order check: the low must appear before the high in the window.
        order_ok = True
        if found_lo and found_hi:
            idx_lo = next(i for i, a in enumerate(chk["amounts_musd"]) if abs(a - lo) < 0.51)
            idx_hi = next(i for i, a in enumerate(chk["amounts_musd"]) if abs(a - hi) < 0.51)
            order_ok = idx_lo < idx_hi
        verdict = (
            "agree" if (found_lo and found_hi and order_ok)
            else "MISMATCH" if chk["amounts_musd"]
            else "no outlook window found"
        )
        rows.append(
            {
                "guided_quarter": r["guided_quarter"],
                "issued_on": r["issued_on"],
                "guide_low_musd": lo,
                "guide_high_musd": hi,
                "guide_mid": r["guide_mid"],
                "anchor_found": chk["anchor"],
                "independent_amounts_musd": chk["amounts_musd"][:6],
                "machine_verified": verdict,
                "needs_manual_check": r["needs_manual_check"],
                "accession": accn,
                "url": r["url"],
            }
        )
        if r["needs_manual_check"]:
            evidence.append(
                f"{'=' * 78}\n"
                f"{r['guided_quarter']}  guidance ${lo:,.0f}m - ${hi:,.0f}m "
                f"(mid ${r['guide_mid']:,.1f}m)\n"
                f"issued {r['issued_on']}   accession {accn}\n"
                f"{r['url']}\n"
                f"machine check: {verdict}   amounts found: {chk['amounts_musd'][:6]}\n"
                f"{'-' * 78}\n"
                f"{chk['window'][:900]}\n"
            )

    out = pd.DataFrame(rows)
    out["verified"] = ""  # reserved for human sign-off
    out.to_csv(sc.MANUAL / "guidance_verified.csv", index=False)
    (sc.MANUAL / "verification_evidence.txt").write_text("\n".join(evidence))

    pd.set_option("display.width", 220, "display.max_colwidth", 60)
    print("Independent re-parse of every quarter's 8-K outlook window\n")
    print(out["machine_verified"].value_counts().to_string())
    print()
    disagree = out[out["machine_verified"] != "agree"]
    if len(disagree):
        print("ROWS NOT CONFIRMED:")
        print(disagree[["guided_quarter", "guide_low_musd", "guide_high_musd",
                        "independent_amounts_musd", "machine_verified"]].to_string(index=False))
    else:
        print("All rows confirmed by the independent parser.")

    print("\nThe 12-row manual worklist:")
    wl = out[out["needs_manual_check"]]
    print(wl[["guided_quarter", "issued_on", "guide_low_musd", "guide_high_musd",
              "guide_mid", "machine_verified"]].to_string(index=False))

    live = out[out["guided_quarter"] == "2026Q3"]
    if len(live):
        r = live.iloc[0]
        print(f"\nHEADLINE NUMBER -- 2026Q3 guidance midpoint ${r['guide_mid']:,.1f}m")
        print(f"  range ${r['guide_low_musd']:,.0f}m - ${r['guide_high_musd']:,.0f}m")
        print(f"  independent parser found: {r['independent_amounts_musd']}")
        print(f"  {r['url']}")

    print(f"\nWrote {(sc.MANUAL / 'guidance_verified.csv').relative_to(sc.REPO)}")
    print(f"Wrote {(sc.MANUAL / 'verification_evidence.txt').relative_to(sc.REPO)}"
          "  <- verbatim windows for the 12 worklist rows")


if __name__ == "__main__":
    main()
