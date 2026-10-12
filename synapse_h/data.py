"""Synthetic regional network and demo scenarios.

All names and values are illustrative. No patient data and no real institution
data are used; the network is a stylized digital twin of one region.
"""

from __future__ import annotations

import copy
import math

from .models import Hospital, Origin

REGION_NAME = "경기 북서부 (Gyeonggi Northwest) · 가상 지역"

ROAD_FACTOR = 1.3
SPEED_KMH = 45.0
HANDOVER_MIN = 3.0

_HOSPITALS = [
    Hospital(
        "H1", "Hanul Regional Center", "권역응급의료센터", 18, 14,
        frozenset({"CT", "CTA", "MRI", "thrombectomy", "neuro_ICU", "trauma_surgery", "OR",
                   "ICU", "cath_lab", "endoscopy", "pediatric_ED"}),
        beds_available=2, hist_accept_rate=0.82, load=0.55, confirm_delay_min=4, feed_age_min=2,
        notes={"stroke": "CTA + 신경중재 전문의 on-call", "trauma": "외상팀 24시간 상주",
               "stemi": "PCI 팀 on-call", "gi_bleed": "소화기내과 on-call"},
    ),
    Hospital(
        "H2", "Mirae Medical Center", "지역응급의료센터", 14, 13,
        frozenset({"CT", "CTA", "MRI", "thrombectomy", "neuro_ICU", "ICU", "cath_lab", "endoscopy"}),
        beds_available=1, hist_accept_rate=0.70, load=0.88, confirm_delay_min=6, feed_age_min=4,
        notes={"stroke": "가까움; 현재 신경계 중환자실 부하 높음", "stemi": "PCI 가능, 대기 있음"},
    ),
    Hospital(
        "H3", "Seobu University Hospital", "권역응급의료센터", 2, 21,
        frozenset({"CT", "CTA", "MRI", "thrombectomy", "neuro_ICU", "trauma_surgery", "OR",
                   "ICU", "cath_lab", "endoscopy", "pediatric_ED", "PICU"}),
        beds_available=3, hist_accept_rate=0.66, load=0.60, confirm_delay_min=11, feed_age_min=1,
        notes={"stroke": "역량 충분; 전원 데스크 응답 느림", "pediatric": "소아 중환자실 보유"},
    ),
    Hospital(
        "H4", "Daon General Hospital", "지역응급의료센터", 8, 6,
        frozenset({"CT", "ICU", "endoscopy", "OR"}),
        beds_available=2, hist_accept_rate=0.78, load=0.50, confirm_delay_min=5, feed_age_min=18,
        notes={"gi_bleed": "응급 내시경 가능"},
    ),
    Hospital(
        "H5", "Saebit Children's Hospital", "소아전문응급센터", 22, 6,
        frozenset({"CT", "MRI", "pediatric_ED", "PICU"}),
        beds_available=1, hist_accept_rate=0.80, load=0.45, confirm_delay_min=5, feed_age_min=26,
        notes={"pediatric": "소아응급 전문의 상주"},
    ),
    Hospital(
        "H6", "Gangseo Heart Center", "심혈관 전문센터", 16, 4,
        frozenset({"CT", "CTA", "cath_lab", "ICU"}),
        beds_available=2, hist_accept_rate=0.85, load=0.40, confirm_delay_min=3, feed_age_min=1,
        notes={"stemi": "Primary PCI 24시간"},
    ),
    Hospital(
        "H7", "Nuri Regional Trauma Center", "권역외상센터", 26, 22,
        frozenset({"CT", "CTA", "trauma_surgery", "OR", "ICU", "neuro_ICU", "endoscopy"}),
        beds_available=2, hist_accept_rate=0.88, load=0.35, confirm_delay_min=3, feed_age_min=3,
        notes={"trauma": "외상 전용 수술실 대기"},
    ),
    Hospital(
        "H8", "Haneul Local Hospital", "지역응급의료기관", 12, 8,
        frozenset({"CT", "endoscopy"}),
        beds_available=3, hist_accept_rate=0.92, load=0.30, confirm_delay_min=2, feed_age_min=6,
        notes={},
    ),
]

_ORIGINS = [
    Origin("O1", "북부 지역병원 A (의뢰기관)", 10, 10),
    Origin("O2", "서부 지역병원 B (의뢰기관)", 4, 14),
    Origin("O3", "동부 지역병원 C (의뢰기관)", 24, 14),
]


def default_network() -> list[Hospital]:
    return copy.deepcopy(_HOSPITALS)


def origins() -> dict[str, Origin]:
    return {o.id: copy.deepcopy(o) for o in _ORIGINS}


def travel_minutes(origin: Origin, hospital: Hospital) -> float:
    dist = math.hypot(origin.x - hospital.x, origin.y - hospital.y)
    return round(HANDOVER_MIN + dist * ROAD_FACTOR / SPEED_KMH * 60, 1)


# Demo referral notes for the semi-final evidence list: stroke, trauma,
# pediatric, plus explicit failure cases (missing fields, out-of-range input,
# no eligible destination).
SCENARIOS: list[dict] = [
    {
        "id": "stroke",
        "title": "뇌졸중 (Stroke)",
        "origin": "O1",
        "note": "72yo male, facial droop, left arm weakness, aphasia. Onset 43 min ago. "
                "BP 160/90, HR 92, SpO2 96%, RR 18. Pre-KTAS 2. NIHSS 14. "
                "Non-contrast CT: no hemorrhage, suspected LVO. Needs CTA and mechanical thrombectomy.",
    },
    {
        "id": "trauma",
        "title": "중증 외상 (Trauma)",
        "origin": "O3",
        "note": "40yo male, high-speed car crash, multi-trauma, intubated. GCS 7. "
                "BP 82/50, HR 128, SpO2 91%. Pre-KTAS 1. FAST positive. Onset 25 min ago.",
    },
    {
        "id": "pediatric",
        "title": "소아 (Pediatric)",
        "origin": "O2",
        "note": "6세 여아, 2층 높이 추락 후 두부 손상, 구토 3회. GCS 13. "
                "혈압 98/60, 맥박 130, 산소포화도 97%. Pre-KTAS 2. 발생 50분 전.",
    },
    {
        "id": "stemi",
        "title": "급성 심근경색 (STEMI)",
        "origin": "O1",
        "note": "58세 남성, 흉통 2시간 지속, 심전도 ST분절 상승(STEMI). "
                "혈압 100/70, 맥박 110, 산소포화도 94%. Pre-KTAS 2. 발생 120분 전.",
    },
    {
        "id": "missing",
        "title": "실패 사례: 필수 항목 누락",
        "origin": "O2",
        "note": "Elderly patient, weak and confused since morning. Family requests transfer.",
    },
    {
        "id": "ood",
        "title": "실패 사례: 범위 밖 입력 (OOD)",
        "origin": "O1",
        "note": "35yo male, chest pain, ST elevation on ECG. BP 400/200, HR 300, SpO2 130%. "
                "Pre-KTAS 2. Onset 30 min ago.",
    },
    {
        "id": "burn",
        "title": "실패 사례: 수용 가능 병원 없음",
        "origin": "O3",
        "note": "45yo male, factory fire, 40% TBSA burn with inhalation injury. "
                "BP 110/70, HR 118, SpO2 92%. Pre-KTAS 1. Onset 35 min ago.",
    },
]


# Concurrent regional demand for the multi-case allocation view
# (already clinician-confirmed fields; listed in arrival order).
CONCURRENT_CASES: list[dict] = [
    {"case_id": "A-1046", "origin_id": "O1", "age": 81, "sex": "female", "pathway": "stroke", "ktas": 3,
     "onset_min": 180, "sbp": 150, "hr": 84, "spo2": 95},
    {"case_id": "A-1047", "origin_id": "O3", "age": 34, "sex": "male", "pathway": "trauma", "ktas": 2,
     "onset_min": 30, "sbp": 104, "hr": 112, "spo2": 95},
    {"case_id": "A-1048", "origin_id": "O1", "age": 72, "sex": "male", "pathway": "stroke", "ktas": 2,
     "onset_min": 43, "sbp": 160, "hr": 92, "spo2": 96},
    {"case_id": "A-1049", "origin_id": "O2", "age": 63, "sex": "male", "pathway": "stemi", "ktas": 2,
     "onset_min": 70, "sbp": 96, "hr": 104, "spo2": 94},
    {"case_id": "A-1050", "origin_id": "O3", "age": 40, "sex": "male", "pathway": "trauma", "ktas": 1,
     "onset_min": 25, "sbp": 82, "hr": 128, "spo2": 91, "gcs": 7},
    {"case_id": "A-1051", "origin_id": "O2", "age": 55, "sex": "female", "pathway": "gi_bleed", "ktas": 3,
     "onset_min": 90, "sbp": 108, "hr": 102, "spo2": 97},
    {"case_id": "A-1052", "origin_id": "O1", "age": 66, "sex": "female", "pathway": "stroke", "ktas": 2,
     "onset_min": 55, "sbp": 172, "hr": 88, "spo2": 97},
]
