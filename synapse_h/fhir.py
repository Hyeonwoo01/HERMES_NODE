"""FHIR exports of a clinician-confirmed case.

Two shapes are produced from the same internal record:

* ``case_bundle`` — FHIR R5 (Patient, Encounter, Observation, Condition,
  ServiceRequest, Organization, Task). Checked against the official R5 schema
  with ``fhir.resources`` (``schema_issues``) and with the HL7 validator in CI.
* ``kr_core_bundle`` — FHIR R4 4.0.1 with KR Core 1.0.2 profiles
  (``hl7.fhir.kr.core``) where a KR Core profile exists for the resource:
  Patient, Encounter, heart rate, pulse oximetry, respiratory rate and blood
  pressure. Checked with the HL7 validator against the KR Core package in CI.
  Resources KR Core has no fitting profile for, or whose required codes we
  cannot honestly fill (HIRA organization identifiers, KCD-8 diagnoses), stay on
  the base R4 definition and do not claim a profile. A blood pressure without a
diastolic value is a panel with ``dataAbsentReason`` and does not claim KR Core
(which requires both values).

``validate_bundle`` is a fast structural self-check (references, core fields)
used inside the app; it does not replace the validators above. No real
patient identifiers are ever written: the patient is a case pseudonym and the
birth year is estimated from age.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .capabilities import PATHWAYS, required_capabilities
from .models import CAPABILITY_LABELS, CaseRecord, Hospital

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
OBS_VALUE = "http://terminology.hl7.org/CodeSystem/v3-ObservationValue"
CLINICAL_STATUS = "http://terminology.hl7.org/CodeSystem/condition-clinical"
VER_STATUS = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
KTAS_SYSTEM = "urn:synapse-h:codesystem:pre-ktas"
CAPABILITY_SYSTEM = "urn:synapse-h:codesystem:capability"
PATHWAY_SYSTEM = "urn:synapse-h:codesystem:pathway"
CASE_ID_SYSTEM = "urn:synapse-h:identifier:case-pseudonym"
HOSPITAL_ID_SYSTEM = "urn:synapse-h:identifier:hospital"
DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"

KR_CORE_PACKAGE = "hl7.fhir.kr.core#1.0.2"
KR = "http://www.hl7korea.or.kr/fhir/krcore/StructureDefinition/"

# attr, LOINC code(s), display, UCUM unit, KR Core profile (R4)
_VITALS = [
    ("hr", ["8867-4"], "Heart rate", "/min", "krcore-heartrate"),
    ("spo2", ["59408-5", "2708-6"], "Oxygen saturation by pulse oximetry", "%", "krcore-pulseoximetry"),
    ("rr", ["9279-1"], "Respiratory rate", "/min", "krcore-respiratoryrate"),
]


def _uuid(rtype: str, rid: str) -> str:
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'synapse-h/{rtype}/{rid}')}"


def _entry(resource: dict) -> dict:
    return {"fullUrl": _uuid(resource["resourceType"], resource["id"]), "resource": resource}


def _ref(rtype: str, rid: str) -> dict:
    return {"reference": _uuid(rtype, rid)}


def _qty(value, unit: str) -> dict:
    return {"value": value, "unit": unit, "system": UCUM, "code": unit}


def _vital_category() -> list[dict]:
    return [{"coding": [{"system": OBS_CATEGORY, "code": "vital-signs", "display": "Vital Signs"}]}]


def _ktas_obs(case: CaseRecord, subject: dict, enc: dict, ts: str) -> dict:
    return {
        "resourceType": "Observation", "id": f"{case.case_id}-ktas", "status": "final",
        "code": {"coding": [{"system": KTAS_SYSTEM, "code": "pre-ktas", "display": "Pre-KTAS level"}],
                 "text": "Pre-KTAS"},
        "subject": subject, "encounter": enc, "effectiveDateTime": ts, "valueInteger": case.ktas,
    }


def _gcs_obs(case: CaseRecord, subject: dict, enc: dict, ts: str) -> dict:
    return {
        "resourceType": "Observation", "id": f"{case.case_id}-gcs", "status": "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "exam", "display": "Exam"}]}],
        "code": {"coding": [{"system": LOINC, "code": "9269-2", "display": "Glasgow coma score total"}]},
        "subject": subject, "encounter": enc, "effectiveDateTime": ts, "valueInteger": case.gcs,
    }


def _vital_obs(case: CaseRecord, attr: str, codes: list[str], display: str, unit: str,
               subject: dict, enc: dict, ts: str) -> dict:
    return {
        "resourceType": "Observation", "id": f"{case.case_id}-{attr}", "status": "final",
        "category": _vital_category(),
        "code": {"coding": [{"system": LOINC, "code": c, "display": display} for c in codes]},
        "subject": subject, "encounter": enc, "effectiveDateTime": ts,
        "valueQuantity": _qty(getattr(case, attr), unit),
    }


def _bp_obs(case: CaseRecord, subject: dict, enc: dict, ts: str) -> dict:
    """Blood pressure panel; a missing diastolic value is marked with dataAbsentReason, never invented."""
    systolic = {"code": {"coding": [{"system": LOINC, "code": "8480-6", "display": "Systolic blood pressure"}]},
                "valueQuantity": _qty(case.sbp, "mm[Hg]")}
    diastolic = {"code": {"coding": [{"system": LOINC, "code": "8462-4", "display": "Diastolic blood pressure"}]}}
    if case.dbp is None:
        diastolic["dataAbsentReason"] = {"coding": [{"system": DATA_ABSENT, "code": "unknown"}]}
    else:
        diastolic["valueQuantity"] = _qty(case.dbp, "mm[Hg]")
    return {
        "resourceType": "Observation", "id": f"{case.case_id}-bp", "status": "final",
        "category": _vital_category(),
        "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}]},
        "subject": subject, "encounter": enc, "effectiveDateTime": ts,
        "component": [systolic, diastolic],
    }


def _condition(case: CaseRecord, subject: dict, enc: dict, onset: str) -> dict:
    pathway = PATHWAYS[case.pathway]
    cond = {
        "resourceType": "Condition", "id": f"{case.case_id}-cond",
        "clinicalStatus": {"coding": [{"system": CLINICAL_STATUS, "code": "active"}]},
        "verificationStatus": {"coding": [{"system": VER_STATUS, "code": "provisional"}]},
        "code": {"coding": [{"system": PATHWAY_SYSTEM, "code": case.pathway, "display": pathway.label}],
                 "text": pathway.label},
        "subject": subject, "encounter": enc, "onsetDateTime": onset,
    }
    if case.red_flags:
        cond["note"] = [{"text": f"Red flags: {', '.join(case.red_flags)}"}]
    return cond


def _organization(h: Hospital) -> dict:
    return {"resourceType": "Organization", "id": h.id, "active": True, "name": h.name,
            "identifier": [{"system": HOSPITAL_ID_SYSTEM, "value": h.id}],
            "type": [{"text": h.tier}]}


def _task(case: CaseRecord, subject: dict, ts: str, destination: Hospital | None) -> dict:
    task = {
        "resourceType": "Task", "id": f"{case.case_id}-transfer", "status": "requested",
        "intent": "order", "code": {"text": "Inter-hospital emergency transfer"},
        "focus": _ref("ServiceRequest", f"{case.case_id}-sr"),
        "for": subject, "authoredOn": ts,
        "note": [{"text": f"Confirmed by: {case.confirmed_by or 'unknown'}"}],
    }
    if destination is not None:
        task["owner"] = _ref("Organization", destination.id)
    return task


def _birth_year(case: CaseRecord, now: datetime) -> str:
    """Only the age is known, so the birth year is an estimate (FHIR allows a year-only date)."""
    return str(now.year - case.age)


def _common(case: CaseRecord, now: datetime | None):
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    onset = (now - timedelta(minutes=case.onset_min)).isoformat(timespec="seconds")
    pid = f"{case.case_id}-pt"
    enc_id = f"{case.case_id}-enc"
    return now, ts, onset, pid, enc_id, _ref("Patient", pid), _ref("Encounter", enc_id)


def case_bundle(case: CaseRecord, destination: Hospital | None = None,
                now: datetime | None = None) -> dict:
    """FHIR R5 collection bundle."""
    now, ts, onset, pid, enc_id, subject, enc = _common(case, now)
    entries = [
        _entry({
            "resourceType": "Patient", "id": pid,
            "meta": {"security": [{"system": OBS_VALUE, "code": "PSEUDED", "display": "pseudonymized"}]},
            "identifier": [{"system": CASE_ID_SYSTEM, "value": case.case_id}],
            "gender": case.sex,
            "birthDate": _birth_year(case, now),
        }),
        _entry({
            "resourceType": "Encounter", "id": enc_id, "status": "in-progress",
            "class": [{"coding": [{"system": ACT_CODE, "code": "EMER", "display": "emergency"}]}],
            "subject": subject,
        }),
        _entry(_ktas_obs(case, subject, enc, ts)),
        _entry(_bp_obs(case, subject, enc, ts)),
    ]
    for attr, codes, display, unit, _ in _VITALS:
        if getattr(case, attr) is not None:
            entries.append(_entry(_vital_obs(case, attr, codes, display, unit, subject, enc, ts)))
    if case.gcs is not None:
        entries.append(_entry(_gcs_obs(case, subject, enc, ts)))
    entries.append(_entry(_condition(case, subject, enc, onset)))

    caps = sorted(required_capabilities(case.pathway, case.age))
    entries.append(_entry({
        "resourceType": "ServiceRequest", "id": f"{case.case_id}-sr", "status": "active",
        "intent": "order", "priority": "stat" if case.ktas <= 2 else "urgent",
        "code": {"concept": {"text": "Inter-hospital emergency transfer"}},
        "orderDetail": [{"parameter": [{
            "code": {"coding": [{"system": CAPABILITY_SYSTEM, "code": c, "display": CAPABILITY_LABELS[c]}]},
            "valueBoolean": True} for c in caps]}],
        "subject": subject, "encounter": enc, "authoredOn": ts,
    }))
    if destination is not None:
        entries.append(_entry(_organization(destination)))
    entries.append(_entry(_task(case, subject, ts, destination)))
    return {"resourceType": "Bundle", "type": "collection", "timestamp": ts, "entry": entries}


def kr_core_bundle(case: CaseRecord, destination: Hospital | None = None,
                   now: datetime | None = None) -> dict:
    """FHIR R4 collection bundle using KR Core 1.0.2 profiles where one fits."""
    now, ts, onset, pid, enc_id, subject, enc = _common(case, now)

    def profiled(resource: dict, profile: str | None) -> dict:
        if profile:
            resource.setdefault("meta", {})["profile"] = [KR + profile]
        return _entry(resource)

    entries = [
        profiled({
            "resourceType": "Patient", "id": pid,
            "meta": {"security": [{"system": OBS_VALUE, "code": "PSEUDED", "display": "pseudonymized"}]},
            "identifier": [{"system": CASE_ID_SYSTEM, "value": case.case_id}],
            "name": [{"text": f"가명 환자 {case.case_id}"}],
            "gender": case.sex,
            "birthDate": _birth_year(case, now),
        }, "krcore-patient"),
        profiled({
            "resourceType": "Encounter", "id": enc_id, "status": "in-progress",
            "class": {"system": ACT_CODE, "code": "EMER", "display": "emergency"},
            "subject": subject,
        }, "krcore-encounter"),
        profiled(_ktas_obs(case, subject, enc, ts), None),
        profiled(_bp_obs(case, subject, enc, ts), "krcore-bloodpressure" if case.dbp is not None else None),
    ]
    for attr, codes, display, unit, profile in _VITALS:
        if getattr(case, attr) is not None:
            entries.append(profiled(_vital_obs(case, attr, codes, display, unit, subject, enc, ts), profile))
    if case.gcs is not None:
        entries.append(profiled(_gcs_obs(case, subject, enc, ts), None))
    entries.append(profiled(_condition(case, subject, enc, onset), None))

    caps = sorted(required_capabilities(case.pathway, case.age))
    entries.append(profiled({
        "resourceType": "ServiceRequest", "id": f"{case.case_id}-sr", "status": "active",
        "intent": "order", "priority": "stat" if case.ktas <= 2 else "urgent",
        "code": {"text": "Inter-hospital emergency transfer"},
        "orderDetail": [{"coding": [{"system": CAPABILITY_SYSTEM, "code": c, "display": CAPABILITY_LABELS[c]}]}
                        for c in caps],
        "subject": subject, "encounter": enc, "authoredOn": ts,
    }, None))
    if destination is not None:
        entries.append(profiled(_organization(destination), None))
    entries.append(profiled(_task(case, subject, ts, destination), None))
    return {"resourceType": "Bundle", "type": "collection", "timestamp": ts, "entry": entries}


# Minimal structural self-check. It catches broken references and missing core
# fields; the official validators run in CI (see scripts/export_fhir_examples.py).
_REQUIRED = {
    "Patient": ("id",),
    "Encounter": ("id", "status", "subject"),
    "Observation": ("id", "status", "code", "subject"),
    "Condition": ("id", "code", "subject"),
    "ServiceRequest": ("id", "status", "intent", "subject"),
    "Organization": ("id", "name"),
    "Task": ("id", "status", "intent"),
}


def _references(node) -> list[str]:
    refs = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference" and isinstance(v, str):
                refs.append(v)
            else:
                refs.extend(_references(v))
    elif isinstance(node, list):
        for v in node:
            refs.extend(_references(v))
    return refs


def validate_bundle(bundle: dict) -> list[str]:
    """Return a list of structural problems (empty list = passes the self-check)."""
    issues = []
    if bundle.get("resourceType") != "Bundle":
        issues.append("resourceType is not Bundle")
    entries = bundle.get("entry", [])
    urls = [e.get("fullUrl") for e in entries]
    if len(set(urls)) != len(urls):
        issues.append("duplicate fullUrl")
    known = set(urls)
    for e in entries:
        r = e.get("resource", {})
        rt = r.get("resourceType")
        if rt not in _REQUIRED:
            issues.append(f"unexpected resourceType: {rt}")
            continue
        for f in _REQUIRED[rt]:
            if not r.get(f):
                issues.append(f"{rt}/{r.get('id')}: missing {f}")
        for ref in _references(r):
            if ref.startswith("urn:uuid:") and ref not in known:
                issues.append(f"{rt}/{r.get('id')}: unresolved reference {ref}")
    return issues


def schema_issues(bundle: dict) -> list[str] | None:
    """Validate an R5 bundle against the official R5 schema (fhir.resources).

    Returns None when fhir.resources is not installed.
    """
    try:
        from fhir.resources.bundle import Bundle
        from pydantic import ValidationError
    except ImportError:
        return None
    try:
        Bundle.model_validate(bundle)
    except ValidationError as exc:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return []
