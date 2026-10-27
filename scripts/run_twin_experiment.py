"""Reproduce the digital-twin baseline and save it with its exact configuration.

    python scripts/run_twin_experiment.py            # default: 20,000 episodes x 10 seeds
    python scripts/run_twin_experiment.py --reps 30

Writes results/twin_baseline.json (machine-readable) and results/twin_baseline.md
(the table quoted in README and docs/PROPOSAL_REVISIONS.md).
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402

from synapse_h.twin import METRICS, TwinParams, replicate, replicate_summary, simulate  # noqa: E402


def git_commit() -> str | None:
    """Short commit hash, suffixed with '+dirty' when the working tree has uncommitted changes."""
    def run(*cmd):
        return subprocess.run(["git", *cmd], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    try:
        commit = run("rev-parse", "--short", "HEAD")
        return commit + ("+dirty" if run("status", "--porcelain", "--", "synapse_h") else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=TwinParams().n_episodes)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    params = replace(TwinParams(), n_episodes=args.episodes)
    summary = simulate(params).summary
    reps = replicate(params, args.reps)
    ci = replicate_summary(reps)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record = {
        "description": "Synthetic digital twin: nearest-appropriate vs Synapse-H (paired episodes). "
                       "No patient data; not clinical validation.",
        "code_commit": git_commit(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "pandas": pd.__version__, "scipy": scipy.__version__},
        "params": asdict(params),
        "single_run": summary.drop(columns=["지표"]).to_dict(orient="records"),
        "replicates": reps.to_dict(orient="records"),
        "replicate_ci95": ci.to_dict(orient="records"),
    }
    (out / "twin_baseline.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    labels = {k: label for k, label, _ in METRICS}
    lines = [
        "# Digital twin baseline (synthetic)",
        "",
        f"`python scripts/run_twin_experiment.py` · {params.n_episodes:,} paired episodes · seed {params.seed} · "
        f"{args.reps} seeds for the confidence intervals · Python {platform.python_version()}, "
        f"numpy {np.__version__}, pandas {pd.__version__}, scipy {scipy.__version__}.",
        "",
        "## Single run (seed %d)" % params.seed,
        "",
        "| Metric | Nearest appropriate | Synapse-H | Paired change |",
        "|---|---|---|---|",
    ]
    for r in summary.itertuples():
        def fmt(v):
            return f"{v * 100:.1f}%" if r.kind == "pct" else f"{v:.2f}"
        lines.append(f"| {labels[r.metric]} | {fmt(r[3])} | {fmt(r[4])} | {r[5]} |")
    lines += ["", f"## Paired difference across {args.reps} seeds (Synapse-H − nearest, 95% CI)", "",
              "| Metric | Mean difference | 95% CI |", "|---|---|---|"]
    scale = {"first_accept": (100, " pp")}
    for r in ci.itertuples():
        k, unit = scale.get(r.metric, (1, ""))
        lines.append(f"| {labels[r.metric]} | {r.mean_diff * k:+.2f}{unit} | "
                     f"[{r.ci_low * k:+.2f}, {r.ci_high * k:+.2f}]{unit} |")
    lines += ["", "The confidence interval reflects simulation randomness only, not whether the model "
              "assumptions are right. See `synapse_h/twin.py` for every assumption."]
    (out / "twin_baseline.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
