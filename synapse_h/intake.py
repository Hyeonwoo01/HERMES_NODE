"""Transfer Intake: schema-constrained extraction with evidence spans.

The extractor *proposes* fields; deterministic validators check range and
presence; a clinician confirms before anything reaches the ranking engine.
The default extractor is rule-based so the demo runs offline. Any approved
private / on-premise model can replace it as long as it returns the same
schema (see ``Extractor``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .capabilities import PATHWAYS, PEDIATRIC_AGE_LIMIT
from .models import CaseRecord, ExtractedField

REQUIRED_FIELDS = ("age", "sex", "pathway", "ktas", "onset_min", "sbp", "hr", "spo2")
OPTIONAL_FIELDS = ("dbp", "rr", "gcs")

FIELD_LABELS = {
    "age": "나이",
    "sex": "성별",
    "pathway": "임상 경로(필요 역량)",
    "ktas": "Pre-KTAS",
    "onset_min": "발병/최종정상 후 경과(분)",
    "sbp": "수축기 혈압 (mmHg)",
    "dbp": "이완기 혈압 (mmHg)",
    "hr": "맥박 (/min)",
    "spo2": "산소포화도 (%)",
    "rr": "호흡수 (/min)",
    "gcs": "GCS",
}

# Plausibility ranges. Values outside are treated as unit/transcription errors.
RANGES: dict[str, tuple[float, float]] = {
    "age": (0, 110),
    "ktas": (1, 5),
    "onset_min": (0, 24 * 60),
    "sbp": (50, 260),
    "dbp": (20, 160),
    "hr": (25, 220),
    "spo2": (50, 100),
    "rr": (4, 60),
    "gcs": (3, 15),
}

RED_FLAGS = {
    "intubated": "기관삽관 상태",
    "삽관": "기관삽관 상태",
    "anticoagul": "항응고제 복용",
    "warfarin": "항응고제 복용",
    "항응고": "항응고제 복용",
    "inhalation injury": "흡입 손상",
    "pregnan": "임신",
    "임신": "임신",
    "seizure": "경련",
    "경련": "경련",
}

_NUM_PATTERNS: dict[str, list[str]] = {
    "age": [r"(\d{1,3})\s*(?:yo\b|y/o|yr\b|years?\s*old|세)", r"\b[MF]\s*/\s*(\d{1,3})\b"],
    "hr": [r"(?:\bHR|\bPR|pulse|맥박|심박수?)\s*[:=]?\s*(\d{2,3})"],
    "spo2": [r"(?:SpO2|SaO2|O2\s*sat|산소포화도)\s*[:=]?\s*(\d{2,3})"],
    "rr": [r"(?:\bRR|호흡수)\s*[:=]?\s*(\d{1,2})"],
    "gcs": [r"GCS\s*[:=]?\s*(\d{1,2})"],
    "ktas": [r"(?:pre-?\s*ktas|ktas)\s*(?:level\s*)?[:=]?\s*(\d)"],
}
_BP = r"(?:\bBP|혈압)\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})"
_ONSET = (r"(?:onset|lkw|last\s+known\s+well|발생|발병|최종\s*정상)\s*[:=]?\s*(\d{1,4})\s*"
          r"(min(?:ute)?s?|분|h(?:ours?|rs?)?|시간)")
_SEX = [
    (r"\b(female|woman|girl)\b|(여성|여자|여아|여\s*\))", "female"),
    (r"\b(male|man|boy)\b|(남성|남자|남아|남\s*\))", "male"),
]


@dataclass
class IntakeResult:
    note: str
    fields: dict[str, ExtractedField]
    red_flags: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return [k for k in REQUIRED_FIELDS if self.fields[k].status == "missing"]

    @property
    def invalid(self) -> list[str]:
        return [k for k, f in self.fields.items() if f.status == "invalid"]

    @property
    def can_proceed(self) -> bool:
        return not self.missing and not self.invalid

    @property
    def abstain_message(self) -> str:
        parts = []
        if self.missing:
            parts.append("필수 항목 누락: " + ", ".join(FIELD_LABELS[k] for k in self.missing))
        if self.invalid:
            parts.append("범위 밖 값(단위·전사 오류 의심): " + ", ".join(FIELD_LABELS[k] for k in self.invalid))
        return " / ".join(parts)


class Extractor(Protocol):
    def extract(self, note: str) -> IntakeResult: ...


def _validate(name: str, value: float) -> tuple[str, str]:
    lo, hi = RANGES.get(name, (float("-inf"), float("inf")))
    if lo <= value <= hi:
        return "extracted", ""
    return "invalid", f"허용 범위 {lo:g}–{hi:g} 밖 — 수동 확인 필요"


class RuleBasedExtractor:
    """Deterministic stand-in for an approved clinical-language model."""

    def extract(self, note: str) -> IntakeResult:
        fields: dict[str, ExtractedField] = {}
        low = note.lower()

        for name, patterns in _NUM_PATTERNS.items():
            fields[name] = self._first_number(name, note, patterns)

        m = re.search(_BP, note, re.IGNORECASE)
        if m:
            for name, grp in (("sbp", 1), ("dbp", 2)):
                val = int(m.group(grp))
                status, msg = _validate(name, val)
                fields[name] = ExtractedField(name, val, status, 0.95, m.group(0), m.span(), msg)
        else:
            fields["sbp"] = ExtractedField("sbp", None, "missing", 0.0)
            fields["dbp"] = ExtractedField("dbp", None, "missing", 0.0)

        fields["onset_min"] = self._onset(note)
        fields["sex"] = self._sex(note)
        fields["pathway"] = self._pathway(low, note, fields["age"].value)

        red = sorted({label for key, label in RED_FLAGS.items() if key in low})
        return IntakeResult(note=note, fields=fields, red_flags=red)

    @staticmethod
    def _first_number(name: str, note: str, patterns: list[str]) -> ExtractedField:
        for pat in patterns:
            m = re.search(pat, note, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                status, msg = _validate(name, val)
                return ExtractedField(name, val, status, 0.95, m.group(0), m.span(), msg)
        return ExtractedField(name, None, "missing", 0.0)

    @staticmethod
    def _onset(note: str) -> ExtractedField:
        m = re.search(_ONSET, note, re.IGNORECASE)
        if not m:
            return ExtractedField("onset_min", None, "missing", 0.0,
                                  message="절대 시각(LKW) 확인 필요")
        val = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("h") or unit == "시간":
            val *= 60
        status, msg = _validate("onset_min", val)
        # Relative times are ambiguous: confidence stays below auto-accept level.
        return ExtractedField("onset_min", val, status, 0.8, m.group(0), m.span(),
                              msg or "상대 시간 — 절대 시각 확인 필요")

    @staticmethod
    def _sex(note: str) -> ExtractedField:
        for pat, label in _SEX:
            m = re.search(pat, note, re.IGNORECASE)
            if m:
                return ExtractedField("sex", label, "extracted", 0.95, m.group(0), m.span())
        return ExtractedField("sex", None, "missing", 0.0)

    @staticmethod
    def _pathway(low: str, note: str, age: int | None) -> ExtractedField:
        best, best_hits, best_span = None, 0, None
        for key, p in PATHWAYS.items():
            hits = [(kw, low.find(kw)) for kw in p.keywords if kw in low]
            if len(hits) > best_hits:
                best, best_hits = key, len(hits)
                kw, pos = min(hits, key=lambda h: h[1])
                best_span = (pos, pos + len(kw))
        if age is not None and age < PEDIATRIC_AGE_LIMIT and best in (None, "trauma", "pediatric"):
            span = best_span or (0, 0)
            return ExtractedField("pathway", "pediatric", "extracted", 0.85,
                                  note[span[0]:span[1]], span, f"{age}세 → 소아 경로 규칙 적용")
        if best is None:
            return ExtractedField("pathway", None, "missing", 0.0,
                                  message="임상 경로를 특정할 근거 없음 — 임상의 선택 필요")
        conf = min(0.95, 0.6 + 0.1 * best_hits)
        return ExtractedField("pathway", best, "extracted", conf,
                              note[best_span[0]:best_span[1]], best_span,
                              f"근거 키워드 {best_hits}개")


def build_case(case_id: str, origin_id: str, values: dict, note: str = "",
               red_flags: list[str] | None = None, confirmed_by: str = "") -> CaseRecord:
    """Create a CaseRecord from clinician-confirmed values; re-validates every field."""
    for name in REQUIRED_FIELDS:
        if values.get(name) in (None, ""):
            raise ValueError(f"필수 항목 누락: {FIELD_LABELS[name]}")
    for name, (lo, hi) in RANGES.items():
        v = values.get(name)
        if v is not None and not (lo <= v <= hi):
            raise ValueError(f"{FIELD_LABELS[name]} 값 {v}이(가) 허용 범위 {lo:g}–{hi:g} 밖입니다")
    if values["pathway"] not in PATHWAYS:
        raise ValueError(f"알 수 없는 임상 경로: {values['pathway']}")
    return CaseRecord(
        case_id=case_id,
        origin_id=origin_id,
        age=int(values["age"]),
        sex=values["sex"],
        pathway=values["pathway"],
        ktas=int(values["ktas"]),
        onset_min=float(values["onset_min"]),
        sbp=int(values["sbp"]),
        hr=int(values["hr"]),
        spo2=int(values["spo2"]),
        dbp=None if values.get("dbp") is None else int(values["dbp"]),
        rr=None if values.get("rr") is None else int(values["rr"]),
        gcs=None if values.get("gcs") is None else int(values["gcs"]),
        red_flags=list(red_flags or []),
        note=note,
        confirmed_by=confirmed_by,
    )
