"""Core data structures shared by every Synapse-H module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODEL_VERSION = "synapse-h-core 0.1.0 · readiness-logit-v0 (synthetic)"

# Capability vocabulary used by the Capability Registry (hard constraints).
CAPABILITY_LABELS: dict[str, str] = {
    "CT": "CT",
    "CTA": "CT 혈관조영(CTA)",
    "MRI": "MRI",
    "thrombectomy": "혈전제거술(신경중재)",
    "neuro_ICU": "신경계 중환자실",
    "trauma_surgery": "외상외과",
    "OR": "응급 수술실",
    "ICU": "성인 중환자실",
    "cath_lab": "심혈관조영실(PCI)",
    "pediatric_ED": "소아 응급실",
    "PICU": "소아 중환자실",
    "endoscopy": "응급 내시경",
    "burn_unit": "화상 전문치료",
}


@dataclass
class Hospital:
    """A receiving node in the regional network (illustrative, not a real institution)."""

    id: str
    name: str
    tier: str
    x: float  # km, stylized regional grid
    y: float
    capabilities: frozenset[str]
    beds_available: int
    hist_accept_rate: float  # historical acceptance rate 0..1
    load: float  # current occupancy / congestion 0..1
    confirm_delay_min: float  # typical transfer-desk response time
    feed_age_min: float  # minutes since the public/hospital feed last updated
    notes: dict[str, str] = field(default_factory=dict)  # capability evidence text

    def has(self, caps: set[str] | frozenset[str]) -> bool:
        return set(caps).issubset(self.capabilities)


@dataclass
class Origin:
    """A referring hospital that initiates the transfer."""

    id: str
    name: str
    x: float
    y: float


@dataclass
class ExtractedField:
    """One schema-constrained field proposed by the intake extractor."""

    name: str
    value: Any
    status: str  # "extracted" | "missing" | "invalid" | "manual"
    confidence: float
    evidence: str = ""
    span: tuple[int, int] | None = None
    message: str = ""


@dataclass
class CaseRecord:
    """A clinician-confirmed, FHIR-ready case (internal normalized schema)."""

    case_id: str
    origin_id: str
    age: int
    sex: str  # "male" | "female"
    pathway: str
    ktas: int
    onset_min: float
    sbp: int
    hr: int
    spo2: int
    dbp: int | None = None
    rr: int | None = None
    gcs: int | None = None
    red_flags: list[str] = field(default_factory=list)
    note: str = ""
    confirmed_by: str = ""

    @property
    def acuity_weight(self) -> float:
        """Higher acuity (lower KTAS) makes delay more expensive for this patient."""
        return {1: 1.6, 2: 1.3, 3: 1.0, 4: 0.8, 5: 0.7}.get(self.ktas, 1.0)


@dataclass
class Readiness:
    """Destination readiness forecast for one hospital and one pathway."""

    accept_prob: float
    low: float
    high: float
    uncertainty: float  # 0..1
    confidence: str  # "high" | "moderate" | "low"
    stale: bool
    freshness_weight: float


@dataclass
class RankedOption:
    rank: int
    hospital: Hospital
    travel_min: float
    readiness: Readiness
    terms: dict[str, float]  # weighted cost terms (minutes-equivalent)
    cost: float
    expected_time_min: float  # confirmation + travel incl. expected retry
    reason: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Excluded:
    hospital: Hospital
    reason: str


@dataclass
class Recommendation:
    case: CaseRecord
    options: list[RankedOption]
    excluded: list[Excluded]
    escalate: bool
    escalation_reason: str
    why_top: str
    model_version: str = MODEL_VERSION
    latency_ms: float = 0.0
    safety_flags: list[str] = field(default_factory=list)
