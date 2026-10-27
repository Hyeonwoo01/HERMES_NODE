"""Score an extractor against the labelled synthetic notes in evals/intake_notes.json.

Each field outcome is one of:
  correct  - proposed value equals the label (including correctly leaving it empty)
  unsafe   - proposed a value that differs from the label (the error a busy clinician might miss)
  missed   - left empty although the note states the value (costs typing, not safety)
Only fields with status "extracted" count as proposed; everything else is left for the clinician.
"""

from __future__ import annotations

import json
from pathlib import Path

from .intake import Extractor

EVAL_PATH = Path(__file__).resolve().parents[1] / "evals" / "intake_notes.json"


def load_notes(path: Path | str = EVAL_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def score(extractor: Extractor, dataset: dict, ids: set[str] | None = None) -> dict:
    fields = dataset["fields"]
    counts = {"correct": 0, "unsafe": 0, "missed": 0}
    per_field = {f: dict(counts) for f in fields}
    errors = []
    n = 0
    for item in dataset["notes"]:
        if ids is not None and item["id"] not in ids:
            continue
        n += 1
        res = extractor.extract(item["note"])
        for f in fields:
            fld = res.fields[f]
            got = fld.value if fld.status == "extracted" else None
            gold = item["gold"][f]
            if got == gold:
                kind = "correct"
            elif got is None:
                kind = "missed"
            else:
                kind = "unsafe"
                errors.append({"id": item["id"], "field": f, "got": got, "gold": gold})
            counts[kind] += 1
            per_field[f][kind] += 1
    total = sum(counts.values())
    return {
        "notes": n,
        "fields": total,
        **counts,
        "accuracy": counts["correct"] / total if total else None,
        "unsafe_rate": counts["unsafe"] / total if total else None,
        "per_field": per_field,
        "unsafe_examples": errors,
    }
