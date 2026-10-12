"""Capability Registry: condition pathways and their hard eligibility constraints.

Hard constraints are applied before any optimization — a hospital without the
required pathway is never made attractive by a short drive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pathway:
    key: str
    label: str
    required: frozenset[str]
    keywords: tuple[str, ...]  # lowercase evidence terms (English + Korean)


PATHWAYS: dict[str, Pathway] = {
    p.key: p
    for p in [
        Pathway(
            "stroke",
            "급성 허혈성 뇌졸중 (Suspected ischemic stroke)",
            frozenset({"CTA", "thrombectomy", "neuro_ICU"}),
            ("facial droop", "hemiparesis", "arm weakness", "aphasia", "slurred speech",
             "nihss", "lvo", "thrombectomy", "stroke", "안면마비", "편마비", "구음장애",
             "실어증", "뇌졸중", "혈전제거"),
        ),
        Pathway(
            "trauma",
            "중증 외상 (Severe trauma)",
            frozenset({"CT", "trauma_surgery", "OR", "ICU"}),
            ("car crash", "motor vehicle", "multi-trauma", "multitrauma", "fast positive",
             "fall from height", "stab", "gunshot", "trauma", "교통사고", "다발성 외상",
             "중증외상", "추락", "자상"),
        ),
        Pathway(
            "stemi",
            "급성 심근경색 (STEMI)",
            frozenset({"cath_lab", "ICU"}),
            ("stemi", "st elevation", "st-elevation", "chest pain", "pci",
             "흉통", "st분절 상승", "심근경색"),
        ),
        Pathway(
            "pediatric",
            "소아 중증 응급 (Pediatric critical)",
            frozenset({"pediatric_ED", "PICU", "CT"}),
            ("child", "pediatric", "infant", "소아", "아동", "영아"),
        ),
        Pathway(
            "gi_bleed",
            "상부위장관 출혈 (Upper GI bleeding)",
            frozenset({"endoscopy", "ICU"}),
            ("hematemesis", "melena", "gi bleed", "variceal", "토혈", "흑색변", "위장관 출혈"),
        ),
        Pathway(
            "burn",
            "중증 화상 (Major burn)",
            frozenset({"burn_unit", "ICU"}),
            ("burn", "tbsa", "화상"),
        ),
    ]
}

PEDIATRIC_AGE_LIMIT = 15


def required_capabilities(pathway: str, age: int | None = None) -> frozenset[str]:
    """Rule library: the pathway defines the requirement; children add pediatric care."""
    caps = set(PATHWAYS[pathway].required)
    if age is not None and age < PEDIATRIC_AGE_LIMIT and pathway != "pediatric":
        caps |= {"pediatric_ED"}
    return frozenset(caps)
