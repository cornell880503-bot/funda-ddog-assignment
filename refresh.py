"""Daily dashboard refresh: top up npm, recompute the monitor, re-render.

    python refresh.py              # incremental -- what you run every day
    python refresh.py --days 30    # re-pull a longer tail (npm revises late data)
    python refresh.py --full       # delegate to run_all.py instead

Why this is not `run_all.py`. The full pipeline re-runs model selection,
walk-forward validation, the permutation null and the bootstrap -- roughly
twenty stages, several minutes, and none of it moves day to day. Those results
are quarterly: they change when a new quarter reports, not when a new day of
downloads lands. Re-running them daily would also mean re-fitting models on
data that grew by one day, which is how a stable finding turns into a drifting
one.

What actually changes daily is the divergence monitor, so this refreshes only
the chain that feeds it:

    fetch_npm      new download days appended to the panel
    npm_clean      outage detection, causal (backward-only) imputation
    build_panel    as-of vintages -- the day-N features for the live quarter
    composite      the tracking call and its backtest
    build/render   payload -> dashboard/index.html + report-zh/dashboard.html

The headline nowcast does not move here either: it is guidance times the
trailing beat, and guidance only changes on an 8-K. If it appears to move, a
new quarter has reported and you want --full.

Requires SEC_CONTACT_EMAIL only for --full; the daily chain hits npm alone.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = str(REPO / ".venv" / "bin" / "python")
if not Path(PY).exists():
    PY = sys.executable

# Ordered: each stage reads what the previous one wrote.
CHAIN = [
    ("fetch_npm.py", "npm daily downloads (incremental)"),
    ("npm_clean.py", "outage detection + causal imputation"),
    ("build_panel.py", "as-of vintage panel"),
    ("composite_tracking.py", "composite tracking call + backtest"),
    ("build_dashboard.py", "assemble payload"),
    ("render_dashboard.py", "-> dashboard/index.html"),
    ("render_dashboard_zh.py", "-> report-zh/dashboard.html"),
]


def since_date(days: int) -> str:
    """Overlap the existing panel rather than appending blindly.

    npm restates recent days for a while after the fact, so re-pulling a tail
    and de-duplicating is more correct than fetching only what is missing.
    """
    return (date.today() - timedelta(days=days)).isoformat()


def run(script: str, args: list[str]) -> float:
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(REPO / "src" / script), *args], capture_output=True, text=True, cwd=REPO
    )
    if proc.returncode != 0:
        print(f"\n  FAILED: {script}\n{proc.stdout[-1200:]}\n{proc.stderr[-2000:]}")
        raise SystemExit(1)
    return time.time() - t0


def main(days: int = 14, full: bool = False) -> None:
    if full:
        raise SystemExit(subprocess.run([PY, str(REPO / "run_all.py")], cwd=REPO).returncode)

    since = since_date(days)
    print(f"Refreshing the monitor (npm tail from {since})\n")
    total = 0.0
    for i, (script, what) in enumerate(CHAIN, 1):
        extra = ["--since", since] if script == "fetch_npm.py" else []
        print(f"[{i}/{len(CHAIN)}] {script:<24} {what}", flush=True)
        total += run(script, extra)

    import json

    payload = json.loads((REPO / "data" / "processed" / "dashboard_payload.json").read_text())
    m, c, imp = payload["meta"], payload["composite"], payload["imputation"]
    call = (
        "tracking ahead" if c["z"] >= c["ahead_threshold"]
        else "tracking behind" if c["z"] <= c["behind_threshold"]
        else "in line"
    )
    print(f"\nDone in {total:.0f}s.")
    print(f"  signal data through   {m['data_through']}  (day {m['days_elapsed']} of {m['days_in_quarter']})")
    print(f"  composite tracking z  {c['z']:+.2f} ({c['horizon']} window) -> {call}")
    print(f"  imputed quarter-to-date  {imp['share_pct']}%  ({imp['days']} of {imp['elapsed']} days)")
    if imp["share_pct"] > 20:
        print("  WARNING: imputed share above 20% -- treat the call as unreliable")
    for f in ("dashboard/index.html", "report-zh/dashboard.html"):
        p = REPO / f
        print(f"  {'ok ' if p.exists() else 'MISSING'} {f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14,
                    help="length of the npm tail to re-pull (default 14)")
    ap.add_argument("--full", action="store_true",
                    help="run the complete pipeline via run_all.py instead")
    main(**vars(ap.parse_args()))
