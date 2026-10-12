"""Safety & Audit: an append-only trace of what the system knew, recommended,
what the user chose, and what happened next."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import MODEL_VERSION, Recommendation

FIRST_CONTACT_MIN = 3.0  # same convention as the digital twin
FAILED_CONTACT_MIN = 6.0


@dataclass
class AuditLog:
    events: list[dict] = field(default_factory=list)

    def _add(self, case_id: str, event: str, **data) -> dict:
        entry = {
            "seq": len(self.events) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "case_id": case_id,
            "event": event,
            "model_version": MODEL_VERSION,
            **data,
        }
        self.events.append(entry)
        return entry

    def recommendation(self, rec: Recommendation, mode: str) -> dict:
        return self._add(
            rec.case.case_id, "recommendation",
            mode=mode,
            pathway=rec.case.pathway,
            ktas=rec.case.ktas,
            options=[{"rank": o.rank, "hospital": o.hospital.id, "cost": round(o.cost, 2),
                      "accept_prob": round(o.readiness.accept_prob, 3),
                      "confidence": o.readiness.confidence} for o in rec.options],
            escalate=rec.escalate,
            latency_ms=round(rec.latency_ms, 2),
        )

    def decision(self, case_id: str, hospital_id: str | None, recommended_rank: int | None,
                 override_reason: str = "", mode: str = "pilot", user: str = "") -> dict:
        if hospital_id is None:
            kind = "escalation"
        elif recommended_rank == 1:
            kind = "select"
        else:
            kind = "override"
        return self._add(case_id, kind, hospital=hospital_id, recommended_rank=recommended_rank,
                         override_reason=override_reason, mode=mode, user=user)

    def contact_outcome(self, case_id: str, hospital_id: str, accepted: bool, reason: str = "") -> dict:
        return self._add(case_id, "contact_outcome", hospital=hospital_id, accepted=accepted, reason=reason)

    # ---- monitoring metrics -------------------------------------------------
    def case_ids(self) -> list[str]:
        return list(dict.fromkeys(e["case_id"] for e in self.events))

    def metrics(self) -> dict:
        decisions = [e for e in self.events if e["event"] in ("select", "override", "escalation")]
        outcomes: dict[str, list[dict]] = {}
        for e in self.events:
            if e["event"] == "contact_outcome":
                outcomes.setdefault(e["case_id"], []).append(e)
        first_accept, conf_times, contacts = [], [], []
        for cid, evs in outcomes.items():
            first_accept.append(evs[0]["accepted"])
            if any(e["accepted"] for e in evs):
                n = next(i for i, e in enumerate(evs) if e["accepted"]) + 1
                contacts.append(n)
                conf_times.append(FIRST_CONTACT_MIN + FAILED_CONTACT_MIN * (n - 1))
        n_dec = len(decisions)
        return {
            "cases": len(self.case_ids()),
            "decisions": n_dec,
            "override_rate": (sum(e["event"] == "override" for e in decisions) / n_dec) if n_dec else None,
            "escalations": len({e["case_id"] for e in self.events
                                if e["event"] == "escalation"
                                or (e["event"] == "recommendation" and e["escalate"])}),
            "first_choice_accept": (sum(first_accept) / len(first_accept)) if first_accept else None,
            "median_confirmation_min": statistics.median(conf_times) if conf_times else None,
            "mean_contacts": statistics.mean(contacts) if contacts else None,
        }
