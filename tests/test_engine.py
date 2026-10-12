import json
from dataclasses import replace

import pytest

from synapse_h.audit import AuditLog
from synapse_h.capabilities import required_capabilities
from synapse_h.data import CONCURRENT_CASES, SCENARIOS, default_network, origins
from synapse_h.fhir import case_bundle
from synapse_h.intake import RuleBasedExtractor, build_case
from synapse_h.optimizer import Weights, allocate, allocate_greedy, rank_destinations
from synapse_h.readiness import predict_readiness
from synapse_h.twin import TwinParams, simulate

SCEN = {s["id"]: s for s in SCENARIOS}
EX = RuleBasedExtractor()


def _case(sid):
    s = SCEN[sid]
    r = EX.extract(s["note"])
    assert r.can_proceed, r.abstain_message
    return build_case(f"T-{sid}", s["origin"], {k: f.value for k, f in r.fields.items()}, s["note"], r.red_flags)


# ---- intake --------------------------------------------------------------

def test_stroke_extraction_fields_and_evidence():
    r = EX.extract(SCEN["stroke"]["note"])
    f = r.fields
    assert (f["age"].value, f["sex"].value, f["pathway"].value) == (72, "male", "stroke")
    assert (f["sbp"].value, f["dbp"].value, f["hr"].value, f["spo2"].value) == (160, 90, 92, 96)
    assert f["ktas"].value == 2 and f["onset_min"].value == 43
    start, end = f["sbp"].span
    assert SCEN["stroke"]["note"][start:end] == f["sbp"].evidence


def test_korean_pediatric_note_routes_to_pediatric_pathway():
    f = EX.extract(SCEN["pediatric"]["note"]).fields
    assert (f["age"].value, f["sex"].value, f["pathway"].value) == (6, "female", "pediatric")
    assert f["onset_min"].value == 50


def test_missing_fields_abstain():
    r = EX.extract(SCEN["missing"]["note"])
    assert not r.can_proceed
    assert "pathway" in r.missing and "ktas" in r.missing


def test_out_of_range_values_are_invalid_not_used():
    r = EX.extract(SCEN["ood"]["note"])
    assert not r.can_proceed
    assert {"sbp", "hr", "spo2"} <= set(r.invalid)
    with pytest.raises(ValueError):
        build_case("X", "O1", {k: f.value for k, f in r.fields.items()})


def test_ktas_is_never_invented():
    r = EX.extract("70yo male, chest pain, ST elevation. BP 120/80, HR 90, SpO2 97%. Onset 20 min ago.")
    assert r.fields["ktas"].status == "missing"


# ---- capability / readiness -----------------------------------------------

def test_child_adds_pediatric_capability():
    assert "pediatric_ED" in required_capabilities("stemi", age=10)
    assert "pediatric_ED" not in required_capabilities("stemi", age=40)


def test_stale_feed_widens_uncertainty_and_shrinks_to_prior():
    h = default_network()[0]
    fresh = predict_readiness(h)
    stale = predict_readiness(replace(h, feed_age_min=40))
    assert stale.stale and not fresh.stale
    assert stale.uncertainty > fresh.uncertainty
    assert abs(stale.accept_prob - 0.5) < abs(fresh.accept_prob - 0.5)


# ---- ranking ---------------------------------------------------------------

def test_hard_constraints_beat_proximity():
    case = _case("stroke")
    rec = rank_destinations(case, default_network(), origins()["O1"])
    ids = [o.hospital.id for o in rec.options]
    assert "H8" not in ids  # nearest hospital but no thrombectomy
    assert all(o.hospital.has(required_capabilities("stroke")) for o in rec.options)
    assert [o.cost for o in rec.options] == sorted(o.cost for o in rec.options)
    assert rec.why_top and len(rec.options) == 3


def test_no_eligible_hospital_escalates():
    rec = rank_destinations(_case("burn"), default_network(), origins()["O3"])
    assert rec.escalate and not rec.options


def test_refused_hospital_is_removed_and_reranked():
    case = _case("stroke")
    first = rank_destinations(case, default_network(), origins()["O1"]).options[0].hospital.id
    rec = rank_destinations(case, default_network(), origins()["O1"], refused={first})
    assert first not in [o.hospital.id for o in rec.options]


def test_unverifiable_feed_is_excluded_and_low_confidence_escalates():
    net = default_network()
    for h in net:
        h.feed_age_min = 50  # stale everywhere but still verifiable
    rec = rank_destinations(_case("stemi"), net, origins()["O1"])
    assert rec.escalate and rec.options  # options kept for reference, flagged
    net[0].feed_age_min = 90
    rec = rank_destinations(_case("stemi"), net, origins()["O1"])
    assert "H1" not in [o.hospital.id for o in rec.options]


def test_weights_change_ranking():
    case = _case("stroke")
    travel_only = Weights(1, 0, 0, 0, 0)
    rec = rank_destinations(case, default_network(), origins()["O1"], weights=travel_only)
    assert rec.options[0].hospital.id == "H2"  # nearest capable


# ---- multi-case ------------------------------------------------------------

def test_global_allocation_respects_capacity_and_beats_greedy():
    net = default_network()
    cases = [build_case(d["case_id"], d["origin_id"], d) for d in CONCURRENT_CASES]
    g = allocate(cases, net, origins())
    gr = allocate_greedy(cases, net, origins())
    used = {}
    for a in g.assignments:
        if a.hospital:
            used[a.hospital.id] = used.get(a.hospital.id, 0) + 1
            assert a.hospital.has(required_capabilities(a.case.pathway, a.case.age))
    assert all(used[h.id] <= h.beds_available for h in net if h.id in used)
    assert g.total_cost <= gr.total_cost + 1e-9


def test_allocation_escalates_when_beds_run_out():
    net = default_network()
    base = dict(CONCURRENT_CASES[4])
    cases = [build_case(f"P{i}", "O3", base) for i in range(8)]  # 8 trauma cases, 7 trauma beds
    g = allocate(cases, net, origins())
    assert g.escalations == 1


# ---- FHIR / audit ----------------------------------------------------------

def test_fhir_bundle_contains_core_resources():
    case = _case("trauma")
    b = case_bundle(case, default_network()[6])
    types = {e["resource"]["resourceType"] for e in b["entry"]}
    assert {"Patient", "Encounter", "Observation", "Condition", "ServiceRequest", "Task",
            "Organization"} <= types
    json.dumps(b)


def test_audit_metrics():
    log = AuditLog()
    rec = rank_destinations(_case("stroke"), default_network(), origins()["O1"])
    log.recommendation(rec, "pilot")
    log.decision("T-stroke", "H2", 2, override_reason="family preference")
    log.contact_outcome("T-stroke", "H2", False, "no bed")
    log.contact_outcome("T-stroke", "H1", True)
    m = log.metrics()
    assert m["override_rate"] == 1.0
    assert m["first_choice_accept"] == 0.0
    assert m["median_confirmation_min"] == 9.0


# ---- digital twin ----------------------------------------------------------

def test_twin_is_reproducible_and_paired():
    p = TwinParams(n_episodes=3000)
    a, b = simulate(p), simulate(p)
    assert a.summary.equals(b.summary)
    ep = a.episodes
    assert (ep["nearest_escalated"] == ep["synapse_escalated"]).all()  # shared acceptance draws


def test_twin_synapse_improves_first_choice_with_informative_prediction():
    s = simulate(TwinParams(n_episodes=5000, prediction_noise=0.3)).summary.set_index("metric")
    assert s.loc["first_accept", "Synapse-H"] > s.loc["first_accept", "Nearest appropriate"]
    assert s.loc["confirmation", "Synapse-H"] < s.loc["confirmation", "Nearest appropriate"]
