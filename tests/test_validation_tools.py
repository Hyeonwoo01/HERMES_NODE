"""Calibration pipeline, usability summaries and FHIR exports."""

import numpy as np

from synapse_h.audit import AuditLog
from synapse_h.calibration import evaluate, fit_readiness, metrics, reliability_table, synthetic_contacts
from synapse_h.data import CONCURRENT_CASES, default_network
from synapse_h.fhir import KR, case_bundle, kr_core_bundle, schema_issues, validate_bundle
from synapse_h.intake import build_case
from synapse_h.usability import cases_from_audit, read_observation_csv, summarize


def test_perfectly_calibrated_scores_have_slope_one_and_intercept_zero():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 20000)
    y = (rng.random(20000) < p).astype(float)
    m = metrics(y, p)
    assert abs(m["calibration_slope"] - 1) < 0.08 and abs(m["calibration_intercept"]) < 0.05
    assert m["ece"] < 0.02
    assert reliability_table(y, p)["n"].sum() == 20000


def test_refit_recovers_the_hidden_model_and_beats_shipped_coefficients():
    df = synthetic_contacts(8000, seed=3)
    coef = fit_readiness(df, l2=0.1)
    assert abs(coef["hist_accept_rate"] - 3.2) < 0.6 and abs(coef["load"] + 1.9) < 0.5
    r = evaluate(df)
    assert r["refit"]["brier"] < r["shipped"]["brier"]
    assert abs(r["refit"]["calibration_intercept"]) < abs(r["shipped"]["calibration_intercept"])


def test_usability_rows_come_from_tagged_cases_only(tmp_path):
    log = AuditLog()
    log.case_opened("A-1", "visible", "kim", at=0, study_participant="P01", study_scenario="stroke")
    log.decision("A-1", "H2", 2, "보호자 요청", at=30)
    log.contact_outcome("A-1", "H2", False, "병상 없음", at=90)
    log.contact_outcome("A-1", "H1", True, at=240)
    log.case_opened("A-2", "visible", "kim", at=300)  # untagged practice case
    rows = cases_from_audit(log.events)
    assert len(rows) == 1 and rows[0]["minutes"] == 4.0 and rows[0]["contacts"] == 2 and rows[0]["overrides"] == 1

    sheet = tmp_path / "usual.csv"
    sheet.write_text("participant,scenario,arm,minutes,contacts,resolved,escalated,safety_errors,missing_items\n"
                     "P01,stroke,usual,9.5,3,yes,no,1,2\nP02,trauma,usual,,4,no,yes,0,1\n", encoding="utf-8")
    s = summarize(rows + read_observation_csv(sheet))
    assert s["usual"]["median_minutes"] == 9.5 and s["usual"]["safety_errors"] == 1
    assert s["synapse-h"]["median_minutes"] == 4.0 and s["synapse-h"]["safety_errors"] is None


def test_fhir_exports_pass_r5_schema_and_claim_kr_core_profiles():
    net = default_network()
    for i, d in enumerate(CONCURRENT_CASES):
        case = build_case(d["case_id"], d["origin_id"], dict(d, dbp=None if i % 2 else 70))
        r5, r4 = case_bundle(case, net[0]), kr_core_bundle(case, net[0])
        assert validate_bundle(r5) == [] and validate_bundle(r4) == []
        assert schema_issues(r5) == []
        profiles = {p for e in r4["entry"] for p in e["resource"].get("meta", {}).get("profile", [])}
        assert KR + "krcore-patient" in profiles and KR + "krcore-encounter" in profiles
        assert (KR + "krcore-bloodpressure" in profiles) == (case.dbp is not None)
        bp = next(e["resource"] for e in r4["entry"] if e["resource"]["id"].endswith("-bp"))
        dia = bp["component"][1]
        assert ("valueQuantity" in dia) != ("dataAbsentReason" in dia)  # never an invented value
        birth = r4["entry"][0]["resource"]["birthDate"]
        assert len(birth) == 4 and birth.isdigit()  # estimated year only
        assert all(e["fullUrl"].startswith("urn:uuid:") and len(e["fullUrl"]) == 45 for e in r4["entry"])
