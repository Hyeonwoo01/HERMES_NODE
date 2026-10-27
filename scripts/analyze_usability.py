"""Summarise a mock-case usability session (docs/VALIDATION_PLAN.md §1).

    python scripts/analyze_usability.py --audit synapse_h_audit.jsonl --observations usual_practice.csv

--audit: the audit log downloaded from the app (cases tagged with a participant code).
--observations: the facilitator's sheet for the usual-practice arm, same columns as
synapse_h.usability.FIELDS. Optional --review CSV adds reviewer-judged safety_errors and
missing_items for the app arm (participant, scenario, safety_errors, missing_items).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synapse_h.usability import cases_from_audit, read_observation_csv, summarize  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    ap.add_argument("--observations")
    ap.add_argument("--review")
    args = ap.parse_args()
    events = [json.loads(line) for line in Path(args.audit).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = cases_from_audit(events)
    if args.review:
        with open(args.review, newline="", encoding="utf-8") as f:
            judged = {(r["participant"], r["scenario"]): r for r in csv.DictReader(f)}
        for r in rows:
            j = judged.get((r["participant"], r["scenario"]))
            if j:
                r["safety_errors"], r["missing_items"] = int(j["safety_errors"]), int(j["missing_items"])
    if args.observations:
        rows += read_observation_csv(args.observations)
    for arm, s in summarize(rows).items():
        print(f"## {arm}")
        for k, v in s.items():
            print(f"- {k}: {'—' if v is None else round(v, 2) if isinstance(v, float) else v}")


if __name__ == "__main__":
    main()
