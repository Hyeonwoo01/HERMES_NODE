"""Summaries for the mock-case usability study in docs/VALIDATION_PLAN.md.

The SYNAPSE-H arm comes from the app's audit log (cases tagged with a
participant code); the usual-practice arm comes from the facilitator's
observation sheet (CSV). Both reduce to the same per-case rows:

    participant, scenario, arm, minutes, contacts, resolved, overrides, escalated,
    safety_errors, missing_items

``safety_errors`` and ``missing_items`` are filled in by an independent reviewer
for both arms (the audit log cannot judge them). With 5-10 participants this
is exploratory: report medians, ranges and every safety error, not p-values.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from .audit import AuditLog

FIELDS = ("participant", "scenario", "arm", "minutes", "contacts", "resolved", "overrides", "escalated",
          "safety_errors", "missing_items")


def cases_from_audit(events: list[dict], arm: str = "synapse-h") -> list[dict]:
    """Per-case rows for study-tagged cases in an exported audit log."""
    log = AuditLog(events=list(events))
    opened = {e["case_id"]: e for e in events if e["event"] == "case_opened" and e.get("study_participant")}
    overrides: dict[str, int] = {}
    for e in events:
        if e["event"] == "override":
            overrides[e["case_id"]] = overrides.get(e["case_id"], 0) + 1
    rows = []
    for tr in log.traces():
        e = opened.get(tr.case_id)
        if e is None:
            continue
        rows.append({
            "participant": e["study_participant"], "scenario": e.get("study_scenario", ""), "arm": arm,
            "minutes": tr.measured_minutes, "contacts": len(tr.contacts), "resolved": tr.resolved,
            "overrides": overrides.get(tr.case_id, 0), "escalated": tr.escalated,
            "safety_errors": None, "missing_items": None,
        })
    return rows


def read_observation_csv(path: str | Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            def num(k, cast=float):
                v = (r.get(k) or "").strip()
                return cast(v) if v else None
            rows.append({
                "participant": r["participant"], "scenario": r.get("scenario", ""), "arm": r.get("arm", "usual"),
                "minutes": num("minutes"), "contacts": num("contacts", int),
                "resolved": (r.get("resolved", "").strip().lower() in ("1", "true", "y", "yes")),
                "overrides": num("overrides", int) or 0,
                "escalated": (r.get("escalated", "").strip().lower() in ("1", "true", "y", "yes")),
                "safety_errors": num("safety_errors", int), "missing_items": num("missing_items", int),
            })
    return rows


def summarize(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        rs = [r for r in rows if r["arm"] == arm]
        mins = [r["minutes"] for r in rs if r["minutes"] is not None and r["resolved"]]
        reviewed = [r for r in rs if r["safety_errors"] is not None]
        out[arm] = {
            "cases": len(rs),
            "participants": len({r["participant"] for r in rs}),
            "resolved": sum(bool(r["resolved"]) for r in rs),
            "median_minutes": statistics.median(mins) if mins else None,
            "max_minutes": max(mins) if mins else None,
            "median_contacts": statistics.median(r["contacts"] for r in rs if r["contacts"] is not None)
            if any(r["contacts"] is not None for r in rs) else None,
            "escalations": sum(bool(r["escalated"]) for r in rs),
            "overrides": sum(r["overrides"] or 0 for r in rs),
            "reviewed_cases": len(reviewed),
            "safety_errors": sum(r["safety_errors"] for r in reviewed) if reviewed else None,
            "missing_items": sum(r["missing_items"] or 0 for r in reviewed) if reviewed else None,
        }
    return out
