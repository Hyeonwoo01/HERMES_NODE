import json
from dataclasses import replace

import pytest

from synapse_h.audit import AuditLog
from synapse_h.capabilities import required_capabilities
from synapse_h.data import CONCURRENT_CASES, SCENARIOS, default_network, origins
from synapse_h.fhir import case_bundle, validate_bundle
from synapse_h.handoff import sbar
from synapse_h.intake import RuleBasedExtractor, build_case
from synapse_h.optimizer import Weights, allocate, allocate_greedy, rank_destinations
from synapse_h.readiness import predict_readiness
from synapse_h.twin import TwinParams, replicate, replicate_summary, simulate

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


def test_negated_and_historical_keywords_do_not_pick_a_pathway():
    r = EX.extract("68세 남성, 흉통 2시간. 뇌졸중 배제됨. ST분절 상승. BP 130/80, HR 90, SpO2 97%.")
    assert r.fields["pathway"].value == "stemi"
    assert any("부정 표현" in n for n in r.notes)
    r = EX.extract("70yo male, history of stroke, now crushing chest pain with ST elevation.")
    assert r.fields["pathway"].value == "stemi"
    assert any("과거력" in n for n in r.notes)
    r = EX.extract("60yo female, no facial droop or arm weakness. chest pain, STEMI on ECG.")
    assert r.fields["pathway"].value == "stemi"


def test_conflicting_pathways_require_clinician_choice():
    r = EX.extract("55yo male, car crash with facial droop and aphasia, hemiparesis, multi-trauma")
    assert r.fields["pathway"].status == "missing" and r.fields["pathway"].value is None
    assert "충돌" in r.fields["pathway"].message and not r.can_proceed


def test_spo2_fraction_and_unclear_onset_are_flagged():
    r = EX.extract("75세 여성 아침부터 편마비, 구음장애. SpO2 0.95")
    assert r.fields["spo2"].status == "invalid" and r.fields["spo2"].value is None
    assert r.fields["onset_min"].status == "missing" and "불명확" in r.fields["onset_min"].message


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


def test_audit_metrics_separate_first_contact_from_model_top1():
    log = AuditLog()
    rec = rank_destinations(_case("stroke"), default_network(), origins()["O1"])
    log.case_opened("T-stroke", "visible", at=1000.0)
    log.recommendation(rec, "visible", at=1001.0)
    log.decision("T-stroke", "H2", 2, override_reason="family preference", at=1010.0)
    log.contact_outcome("T-stroke", "H2", False, "no bed", at=1100.0)  # rank looked up from the decision
    log.decision("T-stroke", "H1", 1, at=1120.0)
    log.contact_outcome("T-stroke", "H1", True, at=1300.0)
    m = log.metrics()
    assert m["override_rate"] == 0.5
    assert m["first_contact_accept"] == 0.0
    assert m["model_top1_accept"] is None  # rank 1 was not the first call
    assert m["mean_contacts"] == 2
    assert m["median_measured_min"] == 5.0  # (1300 - 1000) s
    assert m["median_assumed_min"] == 9.0  # labelled assumption, kept separate
    assert log.events[3]["recommended_rank"] == 2


def test_audit_counts_unresolved_cases():
    log = AuditLog()
    log.case_opened("A", "visible", at=0.0)
    log.decision("A", "H1", 1, at=1.0)
    log.contact_outcome("A", "H1", True, at=60.0)
    log.case_opened("B", "visible", at=0.0)
    log.decision("B", "H1", 1, at=1.0)
    log.contact_outcome("B", "H1", False, "full", at=30.0)
    log.contact_outcome("B", "H2", False, "full", recommended_rank=2, at=90.0)
    m = log.metrics()
    assert m["contacted_cases"] == 2 and m["unresolved_cases"] == 1
    assert m["mean_contacts"] == 1.5  # the unresolved case's two calls count
    assert m["resolved_rate"] == 0.5
    assert m["model_top1_accept"] == 0.5 and m["model_top1_cases"] == 2
    assert m["median_measured_min"] == 1.0  # only resolved cases have a time; unresolved are reported apart


def test_high_acuity_travel_guardrail_escalates():
    net = default_network()
    for h in net:
        if h.id in ("H1", "H2"):  # make the near hospitals unattractive so a far one ranks first
            h.hist_accept_rate, h.load = 0.2, 0.95
        if h.id == "H3":
            h.hist_accept_rate, h.load, h.confirm_delay_min = 0.99, 0.0, 0.0
    case = _case("stroke")
    rec = rank_destinations(case, net, origins()["O1"])
    assert rec.options[0].hospital.id == "H3"
    assert rec.escalate and "travel_guardrail" in rec.safety_flags
    low_acuity = replace(case, ktas=4)
    assert "travel_guardrail" not in rank_destinations(low_acuity, net, origins()["O1"]).safety_flags


# ---- FHIR / handoff --------------------------------------------------------

def test_fhir_bundle_passes_structural_self_check():
    bundle = case_bundle(_case("trauma"), default_network()[6])
    assert validate_bundle(bundle) == []
    bundle["entry"][-1]["resource"]["focus"]["reference"] = "urn:uuid:servicerequest-missing"
    assert any("unresolved reference" in i for i in validate_bundle(bundle))


def test_sbar_uses_only_confirmed_fields():
    case = _case("trauma")
    text = sbar(case, "동부 지역병원 C", default_network()[6], ["Nuri Regional Trauma Center"])
    for tag in ("S (상황)", "B (배경)", "A (평가)", "R (요청)"):
        assert tag in text
    assert "BP 82/50" in text and "Pre-KTAS 1" in text and "기관삽관" in text
    assert "Nuri Regional Trauma Center" in text


# ---- digital twin ----------------------------------------------------------

def test_twin_is_reproducible_and_paired():
    p = TwinParams(n_episodes=3000)
    a, b = simulate(p), simulate(p)
    assert a.summary.equals(b.summary)
    ep = a.episodes
    assert (ep["nearest_escalated"] == ep["synapse_escalated"]).all()  # shared acceptance draws


def test_twin_synapse_improves_first_choice_with_informative_prediction():
    s = simulate(TwinParams(n_episodes=5000, model_error=0.0)).summary.set_index("metric")
    assert s.loc["first_accept", "Synapse-H"] > s.loc["first_accept", "Nearest appropriate"]
    assert s.loc["confirmation", "Synapse-H"] < s.loc["confirmation", "Nearest appropriate"]


def test_twin_gain_shrinks_when_acceptance_is_less_observable():
    def gain(latent):
        s = simulate(TwinParams(n_episodes=8000, latent_noise=latent)).summary.set_index("metric")
        return s.loc["first_accept", "Synapse-H"] - s.loc["first_accept", "Nearest appropriate"]
    assert gain(0.0) > gain(1.5)


def test_twin_replicates_report_confidence_intervals():
    ci = replicate_summary(replicate(TwinParams(n_episodes=2000), n_reps=3)).set_index("metric")
    row = ci.loc["first_accept"]
    assert row.n_seeds == 3 and row.ci_low <= row.mean_diff <= row.ci_high


# ---- business-plan arithmetic ---------------------------------------------

def test_revenue_buildup_rebuilds_each_year_from_drivers():
    from synapse_h.finance import Drivers, revenue_buildup
    bu = revenue_buildup().set_index("연도")
    assert bu.loc["Y1", "build_up"] == 125 + 2 * 15  # one paid pilot + two integrations
    full_year = revenue_buildup(Drivers(new_fraction=1.0)).set_index("연도")
    assert full_year.loc["Y2", "build_up"] > bu.loc["Y2", "build_up"]  # mid-year starts bill less
    assert (bu["gap"] == bu["build_up"] - bu["plan"]).all()


def test_cash_bridge_matches_cumulative_loss_without_collection_lag():
    from synapse_h.finance import cash_bridge
    cb = cash_bridge(70, collection_lag_months=0)
    assert round(cb.min_balance) == 70 - 240 - 180 and cb.min_month == 24  # Y1 + Y2 EBITDA
    assert round(cb.funding_gap) == 350
    assert cash_bridge(70, collection_lag_months=4).funding_gap > cb.funding_gap
