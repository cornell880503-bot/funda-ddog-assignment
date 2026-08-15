"""One command, raw APIs to finished deliverables.

    python run_all.py            # uses cached raw responses where present
    python run_all.py --force    # re-pulls every API (slow, hits SEC/npm)
    python run_all.py --check    # verify only: tests + headline figures

Order matters. Fetchers write data/raw/ and data/processed/; every later stage
reads only from data/processed/, never from an API. That separation is what
makes the run reproducible: with the cache in place the whole pipeline is
offline and deterministic (seeds fixed at model_walkforward.SEED).

No MNPI. Every source is a documented public API or an SEC filing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = str(REPO / ".venv" / "bin" / "python")
if not Path(PY).exists():
    PY = sys.executable

STAGES = [
    # (script, what it does, needs network on a cold cache)
    ("fetch_sec.py", "SEC XBRL company facts -> quarterly target panel", True),
    ("fetch_guidance.py", "8-K EX-99.1 -> guidance + customer counts", True),
    ("audit_guidance.py", "consistency audit + manual verification worklist", False),
    ("fetch_npm.py", "npm daily downloads (Datadog, control, placebo)", True),
    ("fetch_pypi.py", "PyPI 180-day cross-check", True),
    ("npm_clean.py", "outage detection; causal + centred imputation", False),
    ("audit_baskets.py", "constant-composition audit", False),
    ("fetch_hyperscaler.py", "peer earnings dates (timing verification)", True),
    ("fetch_hyperscaler_revenue.py", "peer segment growth from press releases", True),
    ("build_panel.py", "as-of vintage panel + feature construction", False),
    ("analysis_leadlag.py", "stationarity, cross-correlation, partial quarter", False),
    ("analysis_regime.py", "structural break and residual drift", False),
    ("model_walkforward.py", "baselines, 24-cell grid, permutation null, DM", False),
    ("model_hyperscaler.py", "Signal 2 through the identical pipeline", False),
    ("extended_targets.py", "customer growth, billings, RPO targets", False),
    ("revision_critiques.py", "coverage, power, orthogonalised grid", False),
    ("signal_tone.py", "press-release tone + in-document placebo", False),
    ("check_download_mechanism.py", "decoupling mechanism tests", False),
    ("check_pypi_npm_consistency.py", "cross-ecosystem robustness", False),
    ("composite_tracking.py", "composite tracking call + backtest", False),
    ("explore_phase1.py", "overview figures", False),
    ("build_dashboard.py", "assemble dashboard payload", False),
    ("render_dashboard.py", "-> dashboard/index.html", False),
    ("render_dashboard_zh.py", "-> report-zh/dashboard.html", False),
]


def run(script: str, force: bool) -> float:
    cmd = [PY, str(REPO / "src" / script)]
    if force and script.startswith("fetch"):
        cmd.append("--force")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    dt = time.time() - t0
    if proc.returncode != 0:
        print(f"\n  FAILED: {script}\n{proc.stdout[-1500:]}\n{proc.stderr[-2500:]}")
        raise SystemExit(1)
    return dt


def check() -> None:
    import json

    print("Verification\n" + "=" * 62)
    t = subprocess.run([PY, "-m", "pytest", "tests/", "-q"],
                       capture_output=True, text=True, cwd=REPO)
    print("as-of tests:", t.stdout.strip().splitlines()[-1] if t.stdout else "no output")

    payload = json.loads((REPO / "data" / "processed" / "dashboard_payload.json").read_text())
    h, d = payload["headline"], payload["diagnostics"]
    print(f"headline nowcast: ${h['point']}m  [{h['lo']}, {h['hi']}]")
    print(f"cells beating strongest baseline: {d['cells_beating_best']} of {d['grid_cells']}")
    print(f"orthogonalised: {d['cells_beating_best_orth']} of {d['grid_cells']}")
    cz = payload["composite"]["z"]
    assert cz == cz, "composite tracking z is NaN -- horizon/feature-name mismatch"
    print(f"composite tracking z: {cz} ({payload['composite']['horizon']} window)")
    for f in ("report/report.md", "report/slides.md", "dashboard/index.html",
              "report-zh/report.md", "report-zh/slides.md", "report-zh/dashboard.html"):
        p = REPO / f
        print(f"  {'ok ' if p.exists() else 'MISSING'} {f}")


def main(force: bool = False, check_only: bool = False) -> None:
    if check_only:
        check()
        return
    print(f"Running {len(STAGES)} stages "
          f"({'re-pulling all APIs' if force else 'using cached raw responses'})\n")
    total = 0.0
    for i, (script, what, net) in enumerate(STAGES, 1):
        tag = "net" if (net and force) else "   "
        print(f"[{i:2d}/{len(STAGES)}] {tag} {script:<34} {what}", flush=True)
        total += run(script, force)
    print(f"\nDone in {total/60:.1f} min.\n")
    check()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-pull every API")
    ap.add_argument("--check", dest="check_only", action="store_true",
                    help="verify existing outputs only")
    main(**vars(ap.parse_args()))
