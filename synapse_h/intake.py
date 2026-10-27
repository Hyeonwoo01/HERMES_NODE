"""Transfer Intake: schema-constrained extraction with evidence spans.

The extractor *proposes* fields; deterministic validators check range and
presence; a clinician confirms before anything reaches the ranking engine.
The default extractor is rule-based so the demo runs offline. The optional
LLM extractor (``llm_intake.LLMExtractor``) returns the same schema and is
checked against the note and this extractor before anything is shown.
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


# Context rules: a keyword only supports a pathway when it describes a current finding.
NEG_BEFORE = ("no ", "not ", "denies ", "denied ", "negative for ", "without ", "ruled out ", "free of ",
              "absence of ", "absent ")
NEG_AFTER = ("배제", "아님", "아니", "없음", "없고", "없으며", "없다", "없는", "음성", "부인", " ruled out",
             " excluded", " negative", " absent", "(-)")
HIST_BEFORE = ("history of ", "h/o ", "hx of ", "pmh", "past history", "previous ", "prior ", "old ",
               "과거력", "기왕력", "과거 ", "이전 ")
HIST_AFTER = ("과거력", "기왕력", " history", "병력")
UNCLEAR_ONSET = ("unknown onset", "onset unknown", "lkw unknown", "unwitnessed", "wake-up", "woke up with",
                 "this morning", "yesterday", "last night", "발병 시각 불명", "발병 시간 불명", "발생 시각 불명",
                 "시간 모름", "모름", "불명", "아침부터", "어제", "새벽")
_CLAUSE_END = re.compile(r"[.;:,\n]")


def _keyword_context(low: str, pos: int, end: int) -> str:
    """'negated', 'history' or 'current' for the keyword at low[pos:end]."""
    before = low[max(0, pos - 40):pos]
    cut = max((m.end() for m in _CLAUSE_END.finditer(before)), default=0)
    before = before[cut:]
    after = low[end:end + 14]
    m = _CLAUSE_END.search(after)
    after = after[:m.start()] if m else after
    if any(c in before for c in NEG_BEFORE) or any(c in after for c in NEG_AFTER):
        return "negated"
    if any(c in before for c in HIST_BEFORE) or any(c in after for c in HIST_AFTER):
        return "history"
    return "current"


@dataclass
class IntakeResult:
    note: str
    fields: dict[str, ExtractedField]
    red_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # context the clinician should see (negation, history, conflict)
    source: str = "rule"  # which extractor produced the proposals

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

        frac = re.search(r"(?:SpO2|SaO2|O2\s*sat|산소포화도)\s*[:=]?\s*(0?\.\d{1,3})(?!\d)", note, re.IGNORECASE)
        if frac and fields["spo2"].status == "missing":
            fields["spo2"] = ExtractedField("spo2", None, "invalid", 0.0, frac.group(0), frac.span(),
                                            "비율(예: 0.96)로 적힌 것으로 보임 — % 값으로 확인 필요")

        notes: list[str] = []
        fields["onset_min"] = self._onset(note)
        fields["sex"] = self._sex(note)
        fields["pathway"] = self._pathway(low, note, fields["age"].value, notes)

        red = sorted({label for key, label in RED_FLAGS.items() if key in low})
        return IntakeResult(note=note, fields=fields, red_flags=red, notes=notes)

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
            low = note.lower()
            vague = next((c for c in UNCLEAR_ONSET if c in low), None)
            if vague:
                pos = low.find(vague)
                return ExtractedField("onset_min", None, "missing", 0.0, note[pos:pos + len(vague)],
                                      (pos, pos + len(vague)),
                                      f"발병 시각이 불명확함('{vague}') — 마지막 정상 시각(LKW)을 확인해 입력")
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
    def _pathway(low: str, note: str, age: int | None, notes: list[str]) -> ExtractedField:
        scored = []  # (hits, key, first_span)
        for key, p in PATHWAYS.items():
            current, first = set(), None
            for kw in p.keywords:
                for m in re.finditer(re.escape(kw), low):
                    ctx = _keyword_context(low, m.start(), m.end())
                    if ctx == "current":
                        current.add(kw)
                        if first is None or m.start() < first[0]:
                            first = (m.start(), m.end())
                    else:
                        label = "부정 표현" if ctx == "negated" else "과거력"
                        notes.append(f"{label}으로 판단해 제외: '{note[m.start():m.end()]}' ({PATHWAYS[key].label})")
            if current:
                scored.append((len(current), key, first))
        notes[:] = list(dict.fromkeys(notes))
        scored.sort(key=lambda x: -x[0])
        best, best_hits, best_span = (scored[0][1], scored[0][0], scored[0][2]) if scored else (None, 0, None)

        if age is not None and age < PEDIATRIC_AGE_LIMIT and best in (None, "trauma", "pediatric"):
            span = best_span or (0, 0)
            return ExtractedField("pathway", "pediatric", "extracted", 0.85,
                                  note[span[0]:span[1]], span, f"{age}세 → 소아 경로 규칙 적용")
        if best is None:
            return ExtractedField("pathway", None, "missing", 0.0,
                                  message="임상 경로를 특정할 근거 없음 — 임상의 선택 필요")
        if len(scored) > 1:
            second_hits, second = scored[1][0], scored[1][1]
            if second_hits == best_hits or second_hits >= 2:
                msg = (f"경로 근거가 충돌함 ({PATHWAYS[best].label} {best_hits}개 vs "
                       f"{PATHWAYS[second].label} {second_hits}개) — 의료진이 직접 선택")
                notes.append(msg)
                return ExtractedField("pathway", None, "missing", 0.0, message=msg)
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
