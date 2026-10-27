"""Safety & Audit: an append-only trace of what the system knew, recommended,
what the user chose, and what happened next.

Every event carries a wall-clock time so operational metrics are *measured*
from the trace. The 3-minute / 6-minute contact convention of the digital
twin is reported separately and always labelled as an assumption.

The log lives in the Streamlit session (synthetic demo). A real deployment
needs authenticated users, role separation and durable, append-only storage.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import MODEL_VERSION, Recommendation

ENVIRONMENT = "synthetic-demo"
FIRST_CONTACT_MIN = 3.0  # digital-twin assumption, never mixed with measured time
FAILED_CONTACT_MIN = 6.0


@dataclass
class CaseTrace:
    case_id: str
    opened_at: float
    contacts: list[dict] = field(default_factory=list)  # {hospital, rank, accepted, reason, t}
    escalated: bool = False
    recommended_top: str | None = None  # model's rank-1 hospital at the first recommendation

    @property
    def contacted(self) -> bool:
        return bool(self.contacts)

    @property
    def resolved(self) -> bool:
        return any(c["accepted"] for c in self.contacts)

    @property
    def accepted_contact(self) -> dict | None:
        return next((c for c in self.contacts if c["accepted"]), None)

    @property
    def measured_minutes(self) -> float | None:
        acc = self.accepted_contact
        return None if acc is None else (acc["t"] - self.opened_at) / 60

    @property
    def assumed_minutes(self) -> float | None:
        if not self.resolved:
            return None
        n = self.contacts.index(self.accepted_contact) + 1
        return FIRST_CONTACT_MIN + FAILED_CONTACT_MIN * (n - 1)


@dataclass
class AuditLog:
    events: list[dict] = field(default_factory=list)
    environment: str = ENVIRONMENT

    def _add(self, case_id: str, event: str, at: float | None = None, **data) -> dict:
        t = time.time() if at is None else at
        entry = {
            "seq": len(self.events) + 1,
            "t": t,
            "timestamp": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds"),
            "environment": self.environment,
            "case_id": case_id,
            "event": event,
            "model_version": MODEL_VERSION,
            **data,
        }
        self.events.append(entry)
        return entry

    def case_opened(self, case_id: str, mode: str, user: str = "", at: float | None = None) -> dict:
        """The clinician confirmed the case fields; the request clock starts here."""
        return self._add(case_id, "case_opened", at=at, mode=mode, user=user)

    def recommendation(self, rec: Recommendation, mode: str, at: float | None = None) -> dict:
        return self._add(
            rec.case.case_id, "recommendation", at=at,
            mode=mode,
            pathway=rec.case.pathway,
            ktas=rec.case.ktas,
            options=[{"rank": o.rank, "hospital": o.hospital.id, "cost": round(o.cost, 2),
                      "accept_score": round(o.readiness.accept_prob, 3),
                      "confidence": o.readiness.confidence} for o in rec.options],
            escalate=rec.escalate,
            safety_flags=list(rec.safety_flags),
            latency_ms=round(rec.latency_ms, 2),
        )

    def decision(self, case_id: str, hospital_id: str | None, recommended_rank: int | None,
                 override_reason: str = "", mode: str = "", user: str = "", at: float | None = None) -> dict:
        if hospital_id is None:
            kind = "escalation"
        elif recommended_rank == 1:
            kind = "select"
        else:
            kind = "override"
        return self._add(case_id, kind, at=at, hospital=hospital_id, recommended_rank=recommended_rank,
                         override_reason=override_reason, mode=mode, user=user)

    def contact_outcome(self, case_id: str, hospital_id: str, accepted: bool, reason: str = "",
                        recommended_rank: int | None = None, at: float | None = None) -> dict:
        if recommended_rank is None:  # fall back to the rank recorded when the user chose this hospital
            recommended_rank = next((e["recommended_rank"] for e in reversed(self.events)
                                     if e["case_id"] == case_id and e.get("hospital") == hospital_id
                                     and e["event"] in ("select", "override")), None)
        return self._add(case_id, "contact_outcome", at=at, hospital=hospital_id, accepted=accepted,
                         reason=reason, recommended_rank=recommended_rank)

    # ---- per-case reconstruction -------------------------------------------
    def case_ids(self) -> list[str]:
        return list(dict.fromkeys(e["case_id"] for e in self.events))

    def traces(self) -> list[CaseTrace]:
        out: dict[str, CaseTrace] = {}
        for e in self.events:
            tr = out.get(e["case_id"])
            if tr is None:
                tr = out[e["case_id"]] = CaseTrace(e["case_id"], e["t"])
            if e["event"] == "case_opened":
                tr.opened_at = min(tr.opened_at, e["t"])
            elif e["event"] == "recommendation":
                if tr.recommended_top is None and e["options"]:
                    tr.recommended_top = e["options"][0]["hospital"]
                tr.escalated |= bool(e["escalate"] and not e["options"])
            elif e["event"] == "escalation":
                tr.escalated = True
            elif e["event"] == "contact_outcome":
                tr.contacts.append({"hospital": e["hospital"], "rank": e.get("recommended_rank"),
                                    "accepted": e["accepted"], "reason": e.get("reason", ""), "t": e["t"]})
        return list(out.values())

    # ---- monitoring metrics -------------------------------------------------
    def metrics(self) -> dict:
        traces = self.traces()
        decisions = [e for e in self.events if e["event"] in ("select", "override", "escalation")]
        contacted = [t for t in traces if t.contacted]
        top1_first = [t for t in contacted if t.contacts[0]["rank"] == 1]
        resolved = [t for t in contacted if t.resolved]
        measured = [t.measured_minutes for t in resolved]
        assumed = [t.assumed_minutes for t in resolved]

        def rate(num, den):
            return (num / den) if den else None

        return {
            "cases": len(traces),
            "decisions": len(decisions),
            "override_rate": rate(sum(e["event"] == "override" for e in decisions), len(decisions)),
            "escalations": sum(t.escalated for t in traces),
            "contacted_cases": len(contacted),
            # First call accepted, whichever rank the user called first.
            "first_contact_accept": rate(sum(t.contacts[0]["accepted"] for t in contacted), len(contacted)),
            # Model's rank-1 accepted, only for cases where rank 1 was called first.
            "model_top1_accept": rate(sum(t.contacts[0]["accepted"] for t in top1_first), len(top1_first)),
            "model_top1_cases": len(top1_first),
            # All contacted cases count, including ones never accepted.
            "mean_contacts": statistics.mean(len(t.contacts) for t in contacted) if contacted else None,
            "resolved_rate": rate(len(resolved), len(contacted)),
            "unresolved_cases": len(contacted) - len(resolved),
            "median_measured_min": statistics.median(measured) if measured else None,
            "median_assumed_min": statistics.median(assumed) if assumed else None,
        }
