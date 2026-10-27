"""Transfer handoff summary (SBAR) built only from clinician-confirmed fields.

Useful before any prediction is trusted: the transfer nurse can paste the same
structured summary into a call script, message or referral form instead of
re-describing the case to every receiving hospital.
"""

from __future__ import annotations

from .capabilities import PATHWAYS, required_capabilities
from .models import CAPABILITY_LABELS, CaseRecord, Hospital

SEX_KO = {"male": "남", "female": "여"}


def sbar(case: CaseRecord, origin_name: str, destination: Hospital | None = None,
         contacts: list[str] | None = None) -> str:
    caps = ", ".join(CAPABILITY_LABELS[c] for c in sorted(required_capabilities(case.pathway, case.age)))
    vitals = [f"BP {case.sbp}/{case.dbp}" if case.dbp else f"SBP {case.sbp}", f"HR {case.hr}",
              f"SpO2 {case.spo2}%"]
    if case.rr:
        vitals.append(f"RR {case.rr}")
    if case.gcs:
        vitals.append(f"GCS {case.gcs}")
    lines = [
        f"[전원 의뢰 요약 · {case.case_id}]",
        f"S (상황): {PATHWAYS[case.pathway].label} 의심, Pre-KTAS {case.ktas}, 발병/최종정상 후 {case.onset_min:.0f}분",
        f"B (배경): {case.age}세 {SEX_KO[case.sex]} · 의뢰 기관 {origin_name}"
        + (f" · 주의: {', '.join(case.red_flags)}" if case.red_flags else ""),
        f"A (평가): {' · '.join(vitals)}",
        f"R (요청): {caps} 가능 병원으로 전원 요청",
    ]
    if destination is not None:
        lines.append(f"수용 병원: {destination.name}")
    if contacts:
        lines.append(f"연락 이력: {' → '.join(contacts)}")
    lines.append("※ 의료진이 확인한 값만 포함 · 합성 데모 데이터")
    return "\n".join(lines)
