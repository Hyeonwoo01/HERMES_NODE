"""Decision Optimizer: single-case ranking and concurrent multi-case allocation.

Cost (minutes-equivalent) for patient p and hospital h, applied only after
hard capability / capacity constraints:

    w1·T + w2·C + w3·(1−A)·R + w4·L·S_L + w5·U·S_U

T travel, C expected confirmation delay, A predicted acceptance, R the
retry penalty a refusal costs, L load, U uncertainty. For several concurrent
cases the system solves an assignment problem with bed capacity and a
load-concentration (fairness) penalty λ·F(x).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from .capabilities import PATHWAYS, required_capabilities
from .data import travel_minutes
from .models import (CAPABILITY_LABELS, CaseRecord, Excluded, Hospital, Origin, RankedOption,
                     Recommendation)
from .readiness import CONFIDENCE_KO, UNVERIFIABLE_MIN, predict_readiness

RETRY_PENALTY_MIN = 12.0  # failed contact + re-search when a destination refuses
LOAD_SCALE = 10.0
UNCERTAINTY_SCALE = 10.0
# Safety rules. Values are engineering placeholders that a clinical safety
# lead must review before any patient-facing use (see docs/DECISIONS.md).
SAFETY_RULES = {
    # High-acuity patients (Pre-KTAS <= this) routed past the nearest capable
    # hospital by more than the guardrail are escalated, not just annotated.
    "high_acuity_ktas_max": 2,
    "travel_guardrail_min": 10.0,
}
TRAVEL_GUARDRAIL_MIN = SAFETY_RULES["travel_guardrail_min"]

TERM_LABELS = {
    "travel": "이동 시간",
    "confirm": "승인 지연",
    "rejection": "거절 위험",
    "load": "병원 부하",
    "uncertainty": "불확실성",
}


@dataclass
class Weights:
    travel: float = 1.0
    confirm: float = 1.0
    rejection: float = 1.0
    load: float = 1.0
    uncertainty: float = 1.0

    def as_tuple(self) -> tuple[float, ...]:
        return (self.travel, self.confirm, self.rejection, self.load, self.uncertainty)


def eligibility(case: CaseRecord, h: Hospital, refused: set[str] | None = None) -> str | None:
    """Return an exclusion reason, or None if the hospital is eligible."""
    if refused and h.id in refused:
        return "이번 케이스에서 수용 거절됨"
    missing = required_capabilities(case.pathway, case.age) - h.capabilities
    if missing:
        return "필수 역량 없음: " + ", ".join(CAPABILITY_LABELS[c] for c in sorted(missing))
    if h.beds_available <= 0:
        return "가용 병상 없음"
    if h.feed_age_min > UNVERIFIABLE_MIN:
        return f"피드 {h.feed_age_min:.0f}분 미갱신 — 전화 확인 전 제외"
    return None


def cost_terms(travel: float, h: Hospital, accept: float, uncertainty: float,
               w: Weights) -> dict[str, float]:
    return {
        "travel": w.travel * travel,
        "confirm": w.confirm * h.confirm_delay_min,
        "rejection": w.rejection * (1 - accept) * RETRY_PENALTY_MIN,
        "load": w.load * h.load * LOAD_SCALE,
        "uncertainty": w.uncertainty * uncertainty * UNCERTAINTY_SCALE,
    }


_PROS = {"travel": "이동 시간 짧음", "confirm": "전원 데스크 응답 빠름", "rejection": "수용 가능성 높음",
         "load": "현재 부하 낮음", "uncertainty": "데이터 최신·신뢰도 높음"}
_CONS = {"travel": "이동 시간 김", "confirm": "전원 데스크 응답 느림", "rejection": "거절 위험 높음",
         "load": "현재 부하 높음", "uncertainty": "피드 지연·불확실성 높음"}


def _reason(opt: RankedOption, peers: list[RankedOption], pathway: str) -> str:
    parts = []
    note = opt.hospital.notes.get(pathway)
    if note:
        parts.append(note)
    if len(peers) > 1:
        mean = {k: float(np.mean([p.terms[k] for p in peers])) for k in TERM_LABELS}
        delta = {k: opt.terms[k] - mean[k] for k in TERM_LABELS}
        best = min(delta, key=delta.get)
        worst = max(delta, key=delta.get)
        if delta[best] < -0.5:
            parts.append(_PROS[best])
        if delta[worst] > 0.5 and worst != best:
            parts.append(_CONS[worst])
    return "; ".join(dict.fromkeys(parts)) or "역량 충족"


def _why_top(options: list[RankedOption]) -> str:
    top = options[0]
    conf = CONFIDENCE_KO[top.readiness.confidence]
    if len(options) == 1:
        return f"필수 역량을 충족하는 유일한 가용 병원입니다. 신뢰도: {conf}."
    second = options[1]
    dt = second.expected_time_min - top.expected_time_min
    if dt > 0.05:
        return (f"예상 승인+이송 시간이 2순위보다 {dt:.1f}분 짧습니다 "
                f"({top.expected_time_min:.1f} vs {second.expected_time_min:.1f}분). 신뢰도: {conf}.")
    diffs = {k: second.terms[k] - top.terms[k] for k in TERM_LABELS}
    driver = max(diffs, key=diffs.get)
    return (f"2순위보다 예상 시간은 {-dt:.1f}분 길지만 '{TERM_LABELS[driver]}' 항목에서 "
            f"{diffs[driver]:.1f}점 유리해 총 비용이 {second.cost - top.cost:.1f}점 낮습니다. 신뢰도: {conf}.")


def rank_destinations(case: CaseRecord, network: list[Hospital], origin: Origin,
                      weights: Weights | None = None, hour: int = 14,
                      refused: set[str] | None = None, top_k: int = 3) -> Recommendation:
    t0 = time.perf_counter()
    w = weights or Weights()
    candidates: list[RankedOption] = []
    excluded: list[Excluded] = []

    for h in network:
        why_not = eligibility(case, h, refused)
        if why_not:
            excluded.append(Excluded(h, why_not))
            continue
        travel = travel_minutes(origin, h)
        r = predict_readiness(h, hour)
        terms = cost_terms(travel, h, r.accept_prob, r.uncertainty, w)
        expected = travel + h.confirm_delay_min + (1 - r.accept_prob) * RETRY_PENALTY_MIN
        warnings = []
        if r.stale:
            warnings.append(f"피드 {h.feed_age_min:.0f}분 전 갱신 — 하향 가중 적용")
        if r.confidence == "low":
            warnings.append("예측 신뢰도 낮음")
        candidates.append(RankedOption(0, h, travel, r, terms, sum(terms.values()), expected, "", warnings))

    candidates.sort(key=lambda o: o.cost)
    for i, o in enumerate(candidates):
        o.rank = i + 1
    for o in candidates:
        o.reason = _reason(o, candidates, case.pathway)

    options = candidates[:top_k]
    escalate, esc_reason, why = False, "", ""
    safety_flags: list[str] = []
    if not options:
        escalate = True
        esc_reason = (f"'{PATHWAYS[case.pathway].label}' 경로의 필수 역량과 가용 병상을 갖춘 병원이 "
                      "지역 네트워크에 없습니다. 의료지도(Medical Control)로 즉시 에스컬레이션하세요.")
    else:
        why = _why_top(options)
        nearest = min(c.travel_min for c in candidates)
        top = options[0]
        extra = top.travel_min - nearest
        if case.ktas <= SAFETY_RULES["high_acuity_ktas_max"] and extra > SAFETY_RULES["travel_guardrail_min"]:
            top.warnings.append(f"가장 가까운 적합 병원보다 {extra:.0f}분 더 멂 — 임상 근거 확인")
            safety_flags.append("travel_guardrail")
            escalate = True
            esc_reason = (f"고위험 환자(Pre-KTAS {case.ktas})의 1순위가 가장 가까운 적합 병원보다 {extra:.0f}분 더 "
                          "멉니다. 이 순위를 그대로 따르지 말고 의료지도 확인 후 결정하세요.")
        if top.readiness.confidence == "low":
            safety_flags.append("low_confidence")
            escalate = True
            esc_reason = (esc_reason + " " if esc_reason else "") + (
                "1순위 추천의 불확실성이 임계값을 넘었습니다. 순위는 참고용이며 의료지도 확인 후 결정하세요.")

    if not options:
        safety_flags.append("no_eligible")
    return Recommendation(case, options, excluded, escalate, esc_reason, why,
                          latency_ms=(time.perf_counter() - t0) * 1000, safety_flags=safety_flags)


# --------------------------------------------------------------------------
# Concurrent multi-case allocation
# --------------------------------------------------------------------------

ESCALATE = "ESCALATE"
_INFEASIBLE = 1e6
_ESCALATION_COST = 1e4


@dataclass
class Assignment:
    case: CaseRecord
    hospital: Hospital | None  # None → escalate to medical control
    cost: float  # unweighted single-case cost at the assigned hospital
    weighted_cost: float  # acuity-weighted cost
    individual_rank: int | None  # rank of the assigned hospital in the case's own list
    travel_min: float | None
    accept_prob: float | None


@dataclass
class Allocation:
    assignments: list[Assignment]
    total_cost: float
    fairness_penalty: float
    method: str

    @property
    def escalations(self) -> int:
        return sum(a.hospital is None for a in self.assignments)


def _cost_table(cases, network, origins_by_id, w, hour):
    """cost[i][j] for case i and hospital j (np.inf if ineligible) and per-case ranks."""
    n, m = len(cases), len(network)
    cost = np.full((n, m), np.inf)
    meta = {}
    for i, c in enumerate(cases):
        origin = origins_by_id[c.origin_id]
        for j, h in enumerate(network):
            if eligibility(c, h):
                continue
            travel = travel_minutes(origin, h)
            r = predict_readiness(h, hour)
            cost[i, j] = sum(cost_terms(travel, h, r.accept_prob, r.uncertainty, w).values())
            meta[i, j] = (travel, r.accept_prob)
    ranks = np.argsort(np.argsort(cost, axis=1), axis=1) + 1
    return cost, meta, ranks


def _fairness(counts: dict[int, int], lam: float) -> float:
    return lam * sum(k * (k - 1) / 2 for k in counts.values())


def _build(cases, network, cost, meta, ranks, choice, lam, method) -> Allocation:
    out, total, counts = [], 0.0, {}
    for i, j in enumerate(choice):
        c = cases[i]
        if j is None:
            out.append(Assignment(c, None, float("nan"), float("nan"), None, None, None))
            total += _ESCALATION_COST
            continue
        counts[j] = counts.get(j, 0) + 1
        travel, acc = meta[i, j]
        wc = c.acuity_weight * cost[i, j]
        total += wc
        out.append(Assignment(c, network[j], float(cost[i, j]), float(wc), int(ranks[i, j]), travel, acc))
    fair = _fairness(counts, lam)
    return Allocation(out, total + fair, fair, method)


def allocate(cases: list[CaseRecord], network: list[Hospital], origins_by_id: dict[str, Origin],
             weights: Weights | None = None, fairness_lambda: float = 3.0, hour: int = 14) -> Allocation:
    """Globally optimal assignment under bed capacity with a concentration penalty.

    Each hospital is expanded into bed slots; the k-th patient sent to the same
    hospital pays an extra λ·k, so the slot expansion reproduces the convex
    fairness term exactly and the Hungarian algorithm returns the optimum.
    """
    w = weights or Weights()
    cost, meta, ranks = _cost_table(cases, network, origins_by_id, w, hour)
    n = len(cases)
    cols, slot_owner = [], []
    for j, h in enumerate(network):
        for k in range(min(h.beds_available, n)):
            col = np.where(np.isfinite(cost[:, j]),
                           cost[:, j] * np.array([c.acuity_weight for c in cases]) + fairness_lambda * k,
                           _INFEASIBLE)
            cols.append(col)
            slot_owner.append(j)
    for _ in range(n):  # escalation slots
        cols.append(np.full(n, _ESCALATION_COST))
        slot_owner.append(None)
    matrix = np.column_stack(cols)
    rows, chosen = linear_sum_assignment(matrix)
    choice: list[int | None] = [None] * n
    for r, col in zip(rows, chosen):
        choice[r] = slot_owner[col]
    return _build(cases, network, cost, meta, ranks, choice, fairness_lambda, "global")


def allocate_greedy(cases: list[CaseRecord], network: list[Hospital], origins_by_id: dict[str, Origin],
                    weights: Weights | None = None, fairness_lambda: float = 3.0, hour: int = 14) -> Allocation:
    """Baseline: first-come, each case takes its own best remaining hospital."""
    w = weights or Weights()
    cost, meta, ranks = _cost_table(cases, network, origins_by_id, w, hour)
    beds = [h.beds_available for h in network]
    choice: list[int | None] = []
    for i in range(len(cases)):
        order = [j for j in np.argsort(cost[i]) if np.isfinite(cost[i, j]) and beds[j] > 0]
        if order:
            beds[order[0]] -= 1
            choice.append(int(order[0]))
        else:
            choice.append(None)
    return _build(cases, network, cost, meta, ranks, choice, fairness_lambda, "greedy")
