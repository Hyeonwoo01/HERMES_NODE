"""FHIR R5-shaped case bundle export.

The internal schema stays normalized; this adapter exposes the confirmed case
as Patient, Encounter, Observation, Condition, ServiceRequest, Organization
and Task resources so a partner that supports FHIR can consume it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .capabilities import PATHWAYS, required_capabilities
from .models import CAPABILITY_LABELS, CaseRecord, Hospital

LOINC = "http://loinc.org"
KTAS_SYSTEM = "urn:synapse-h:codesystem:pre-ktas"
CAPABILITY_SYSTEM = "urn:synapse-h:codesystem:capability"
PATHWAY_SYSTEM = "urn:synapse-h:codesystem:pathway"

_VITALS = [
    ("sbp", "8480-6", "Systolic blood pressure", "mm[Hg]"),
    ("dbp", "8462-4", "Diastolic blood pressure", "mm[Hg]"),
    ("hr", "8867-4", "Heart rate", "/min"),
    ("spo2", "59408-5", "Oxygen saturation by pulse oximetry", "%"),
    ("rr", "9279-1", "Respiratory rate", "/min"),
    ("gcs", "9269-2", "Glasgow coma score total", "{score}"),
]


def _entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource['resourceType'].lower()}-{resource['id']}", "resource": resource}


def case_bundle(case: CaseRecord, destination: Hospital | None = None,
                now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    pid = f"{case.case_id}-pt"
    patient_ref = {"reference": f"urn:uuid:patient-{pid}"}
    enc_id = f"{case.case_id}-enc"
    entries = [
        _entry({
            "resourceType": "Patient", "id": pid,
            "meta": {"security": [{"code": "PSEUDED", "display": "pseudonymized"}]},
            "gender": case.sex,
            "extension": [{"url": "urn:synapse-h:age-years", "valueInteger": case.age}],
        }),
        _entry({
            "resourceType": "Encounter", "id": enc_id, "status": "in-progress",
            "class": [{"coding": [{"code": "EMER", "display": "emergency"}]}],
            "subject": patient_ref,
        }),
    ]
    enc_ref = {"reference": f"urn:uuid:encounter-{enc_id}"}

    entries.append(_entry({
        "resourceType": "Observation", "id": f"{case.case_id}-ktas", "status": "final",
        "code": {"coding": [{"system": KTAS_SYSTEM, "code": "pre-ktas", "display": "Pre-KTAS level"}]},
        "subject": patient_ref, "encounter": enc_ref, "effectiveDateTime": ts,
        "valueInteger": case.ktas,
    }))
    for attr, code, display, unit in _VITALS:
        value = getattr(case, attr)
        if value is None:
            continue
        entries.append(_entry({
            "resourceType": "Observation", "id": f"{case.case_id}-{attr}", "status": "final",
            "category": [{"coding": [{"code": "vital-signs"}]}],
            "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
            "subject": patient_ref, "encounter": enc_ref, "effectiveDateTime": ts,
            "valueQuantity": {"value": value, "unit": unit},
        }))

    onset = (now - timedelta(minutes=case.onset_min)).isoformat(timespec="seconds")
    pathway = PATHWAYS[case.pathway]
    entries.append(_entry({
        "resourceType": "Condition", "id": f"{case.case_id}-cond",
        "verificationStatus": {"coding": [{"code": "provisional"}]},
        "code": {"coding": [{"system": PATHWAY_SYSTEM, "code": case.pathway, "display": pathway.label}]},
        "subject": patient_ref, "encounter": enc_ref, "onsetDateTime": onset,
        "note": [{"text": f"Red flags: {', '.join(case.red_flags)}"}] if case.red_flags else [],
    }))
    caps = sorted(required_capabilities(case.pathway, case.age))
    entries.append(_entry({
        "resourceType": "ServiceRequest", "id": f"{case.case_id}-sr", "status": "active",
        "intent": "order", "priority": "stat" if case.ktas <= 2 else "urgent",
        "code": {"concept": {"coding": [
            {"system": CAPABILITY_SYSTEM, "code": c, "display": CAPABILITY_LABELS[c]} for c in caps]}},
        "subject": patient_ref, "encounter": enc_ref, "authoredOn": ts,
    }))

    task = {
        "resourceType": "Task", "id": f"{case.case_id}-transfer", "status": "requested",
        "intent": "order", "code": {"text": "Inter-hospital emergency transfer"},
        "focus": {"reference": f"urn:uuid:servicerequest-{case.case_id}-sr"},
        "for": patient_ref, "authoredOn": ts,
        "note": [{"text": f"Confirmed by: {case.confirmed_by or 'unknown'}"}],
    }
    if destination is not None:
        entries.append(_entry({
            "resourceType": "Organization", "id": destination.id, "name": destination.name,
            "type": [{"text": destination.tier}],
        }))
        task["owner"] = {"reference": f"urn:uuid:organization-{destination.id}"}
    entries.append(_entry(task))

    return {"resourceType": "Bundle", "type": "collection", "timestamp": ts, "entry": entries}
