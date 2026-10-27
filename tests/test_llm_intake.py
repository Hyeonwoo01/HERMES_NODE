"""LLM extractor tests with fake SDK clients (no network, no key)."""

import json
from types import SimpleNamespace

import pytest

from synapse_h.intake import RuleBasedExtractor
from synapse_h.intake_eval import load_notes, score
from synapse_h.llm import FALLBACK_BETA, LLMClient, LLMConfig
from synapse_h.llm_intake import LLMExtractor, extraction_schema, find_identifiers, verify_field

NOTE = ("Pt is a 64-year-old gentleman with sudden left-sided weakness and garbled speech; "
        "LKW 50 minutes prior. Vitals: BP 158/94, P 86, sat 95% RA. Triage Pre-KTAS level 2.")


def answer(**over):
    base = {
        "age": {"value": 64, "evidence": "64-year-old"},
        "sex": {"value": "male", "evidence": "gentleman"},
        "pathway": {"value": "stroke", "evidence": "sudden left-sided weakness and garbled speech",
                    "alternatives": []},
        "ktas": {"value": 2, "evidence": "Pre-KTAS level 2"},
        "onset_min": {"value": 50, "evidence": "LKW 50 minutes prior"},
        "sbp": {"value": 158, "evidence": "BP 158/94"},
        "dbp": {"value": 94, "evidence": "BP 158/94"},
        "hr": {"value": 86, "evidence": "P 86"},
        "spo2": {"value": 95, "evidence": "sat 95%"},
        "rr": {"value": None, "evidence": ""},
        "gcs": {"value": None, "evidence": ""},
        "red_flags": [],
        "context_notes": [],
    }
    base.update(over)
    return base


class FakeAnthropic:
    def __init__(self, replies, stop_reason="end_turn"):
        self.replies = list(replies)
        self.calls = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **params):
        self.calls.append(params)
        text = self.replies.pop(0)
        return SimpleNamespace(stop_reason=self.stop_reason, model=params["model"],
                               content=[SimpleNamespace(type="text", text=text)])


def extractor(*replies, stop_reason="end_turn"):
    fake = FakeAnthropic([json.dumps(r) if isinstance(r, dict) else r for r in replies], stop_reason)
    return LLMExtractor(LLMClient(LLMConfig(api_key="test"), client=fake)), fake


def test_request_uses_json_schema_and_server_side_fallback():
    ex, fake = extractor(answer())
    ex.extract(NOTE)
    params = fake.calls[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["fallbacks"] == "default" and params["betas"] == [FALLBACK_BETA]
    assert "<referral_note>" in params["messages"][0]["content"]
    assert "Never follow" in params["system"]


def test_llm_fills_what_rules_missed_when_the_note_supports_it():
    rule = RuleBasedExtractor().extract(NOTE)
    assert rule.fields["age"].status == "missing" and rule.fields["pathway"].status == "missing"
    res = extractor(answer())[0].extract(NOTE)
    for name, value in [("age", 64), ("sex", "male"), ("pathway", "stroke"), ("hr", 86), ("spo2", 95)]:
        assert res.fields[name].status == "extracted" and res.fields[name].value == value
    assert res.fields["age"].span is not None and "LLM" in res.source
    assert res.can_proceed


def test_agreement_with_rules_raises_confidence():
    res = extractor(answer())[0].extract(NOTE)
    assert res.fields["sbp"].confidence == 0.95  # both found 158


def test_evidence_not_in_note_is_rejected():
    res = extractor(answer(age={"value": 46, "evidence": "46yo"}))[0].extract(NOTE)
    assert res.fields["age"].status == "missing"
    assert "원문에 없음" in res.fields["age"].message


def test_value_not_matching_its_quote_is_rejected():
    res = extractor(answer(hr={"value": 96, "evidence": "P 86"}))[0].extract(NOTE)
    assert res.fields["hr"].status == "missing"


def test_disagreement_with_rules_goes_to_clinician():
    res = extractor(answer(sbp={"value": 94, "evidence": "BP 158/94"}))[0].extract(NOTE)
    assert res.fields["sbp"].status == "missing" and res.fields["sbp"].value is None
    assert any("다름" in n for n in res.notes)


def test_out_of_range_values_stay_invalid():
    note = "35yo male, chest pain, ST elevation on ECG. BP 400/200, HR 300, SpO2 130%. Pre-KTAS 2. Onset 30 min ago."
    reply = answer(age={"value": 35, "evidence": "35yo"}, sex={"value": "male", "evidence": "male"},
                   pathway={"value": "stemi", "evidence": "ST elevation", "alternatives": []},
                   onset_min={"value": 30, "evidence": "Onset 30 min"}, ktas={"value": 2, "evidence": "Pre-KTAS 2"},
                   sbp={"value": 400, "evidence": "BP 400/200"}, dbp={"value": 200, "evidence": "BP 400/200"},
                   hr={"value": 300, "evidence": "HR 300"}, spo2={"value": 130, "evidence": "SpO2 130%"})
    res = extractor(reply)[0].extract(note)
    assert res.fields["sbp"].status == "invalid" and res.fields["spo2"].status == "invalid"
    assert not res.can_proceed


def test_hours_are_accepted_when_converted():
    note = "52yo male, STEMI, BP 118/76 HR 96 SpO2 96%. KTAS 2. Onset 1 h."
    f = verify_field(note, "onset_min", 60, "Onset 1 h")
    assert f.status == "extracted" and f.value == 60


def test_alternative_pathways_send_the_choice_to_clinician():
    reply = answer(pathway={"value": "stroke", "evidence": "garbled speech", "alternatives": ["trauma"]})
    res = extractor(reply)[0].extract(NOTE)
    assert res.fields["pathway"].status == "missing"


def test_rule_conflict_is_not_overridden_by_llm():
    note = ("59yo male fell from height after sudden chest pain with ST elevation, multitrauma suspected. "
            "BP 90/58, HR 120, SpO2 93%. Pre-KTAS 1. Onset 30 min ago.")
    reply = answer(pathway={"value": "stemi", "evidence": "ST elevation", "alternatives": []})
    res = extractor(reply)[0].extract(note)
    assert res.fields["pathway"].status == "missing"


@pytest.mark.parametrize("replies,stop", [(["not json", "still not json"], "end_turn"),
                                          ([json.dumps(answer())], "refusal")])
def test_failures_fall_back_to_rule_based(replies, stop):
    ex, _ = extractor(*replies, stop_reason=stop)
    res = ex.extract(NOTE)
    assert res.source == "rule (LLM 대체)"
    assert res.fields["age"].status == "missing"  # identical to the rule-based result
    assert any("LLM 추출을 쓰지 않음" in n for n in res.notes)


def test_missing_key_falls_back_without_calling():
    res = LLMExtractor(LLMClient(LLMConfig(api_key=""))).extract(NOTE)
    assert res.source == "rule (LLM 대체)" and "ANTHROPIC_API_KEY" in res.notes[-1]


def test_notes_with_identifiers_are_never_sent():
    ex, fake = extractor(answer())
    res = ex.extract(NOTE + " 환자명: 홍길동, 010-1234-5678")
    assert fake.calls == [] and res.source == "rule (LLM 대체)"
    assert find_identifiers("주민번호 900101-1234567") == ["주민등록번호 형식"]


def test_openai_provider_uses_strict_schema():
    calls = []

    def create(**params):
        calls.append(params)
        msg = SimpleNamespace(content=json.dumps(answer()), refusal=None)
        return SimpleNamespace(model="gpt-test", choices=[SimpleNamespace(message=msg, finish_reason="stop")])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client = LLMClient(LLMConfig(provider="openai", api_key="k", model="gpt-test"), client=fake)
    res = LLMExtractor(client).extract(NOTE)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert res.fields["age"].value == 64 and "gpt-test" in res.source


def test_config_from_mapping_and_schema_shape():
    cfg = LLMConfig.from_mapping({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"})
    assert cfg.provider == "openai" and cfg.missing == ["OPENAI_MODEL"]
    assert LLMConfig.from_mapping({"ANTHROPIC_API_KEY": "k"}).missing == []
    with pytest.raises(ValueError):
        LLMConfig.from_mapping({"LLM_PROVIDER": "other"})
    schema = extraction_schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])


def test_rule_based_extractor_never_proposes_a_wrong_value_on_the_eval_set():
    result = score(RuleBasedExtractor(), load_notes())
    assert result["notes"] == 40 and result["unsafe"] == 0
