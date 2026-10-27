"""Public emergency-data adapter tests (bundled synthetic XML, no network)."""

from datetime import datetime, timedelta

import pytest

from synapse_h.data import SCENARIOS
from synapse_h.intake import RuleBasedExtractor, build_case
from synapse_h.optimizer import rank_destinations
from synapse_h.public_feed import (KST, NEMCClient, PublicFeedError, build_network, flag, load_region,
                                   parse_items, sample_client)


@pytest.fixture
def snap():
    return load_region(sample_client(), "가상도")


def test_flags_treat_unknown_as_not_available():
    assert flag("Y") is True and flag("\xa0Y\xa0") is True and flag("가능") is True
    assert flag("N1") is False and flag("불가능") is False
    assert flag("정보미제공") is None and flag("") is None and flag(None) is None


def test_capabilities_come_only_from_reported_fields(snap):
    by = {h.id: h for h in snap.hospitals}
    assert {"thrombectomy", "neuro_ICU", "CTA", "cath_lab"} <= by["X9000001"].capabilities
    assert "burn_unit" not in by["X9000001"].capabilities  # 불가능
    assert "thrombectomy" not in by["X9000004"].capabilities  # 정보미제공 -> not granted
    assert "trauma_surgery" not in set().union(*(h.capabilities for h in snap.hospitals))  # not in the API
    assert "뇌경색 재관류중재술 수용" in snap.unknown["X9000004"]


def test_provenance_freshness_and_assumptions(snap):
    h = next(h for h in snap.hospitals if h.id == "X9000001")
    assert h.source.startswith("국립중앙의료원") and h.updated_at
    assert 2 <= h.feed_age_min <= 5
    assert h.hist_accept_rate == 0.70 and any("가정값" in a for a in h.assumed)
    assert h.load == pytest.approx(1 - 4 / 30, abs=0.01)
    stale = next(h for h in snap.hospitals if h.id == "X9000006")
    assert stale.feed_age_min > 60


def test_live_network_runs_through_the_ranking_engine(snap):
    note = SCENARIOS[0]["note"]
    vals = {k: f.value for k, f in RuleBasedExtractor().extract(note).fields.items()}
    case = build_case("L-1", "X9000007", vals)
    rec = rank_destinations(case, snap.hospitals, snap.origins["X9000007"])
    assert rec.options and rec.options[0].hospital.id in {"X9000001", "X9000002", "X9000003"}
    excluded = {e.hospital.id: e.reason for e in rec.excluded}
    assert "X9000006" in excluded  # stale feed (95 min) is never ranked


def test_trauma_needs_a_regional_designation_list():
    c = sample_client()
    args = (c.directory("가상도"), c.beds("가상도"), c.severe("가상도"))
    plain = build_network(*args)
    designated = build_network(*args, capability_overrides={"X9000003": {"trauma_surgery"}})
    assert not any("trauma_surgery" in h.capabilities for h in plain.hospitals)
    h = next(h for h in designated.hospitals if h.id == "X9000003")
    assert "trauma_surgery" in h.capabilities and "지역 지정 목록" in h.notes["trauma"]


def test_provider_errors_are_raised():
    with pytest.raises(PublicFeedError, match="resultCode=03"):
        parse_items("<response><header><resultCode>03</resultCode><resultMsg>NODATA_ERROR</resultMsg></header></response>")
    with pytest.raises(PublicFeedError, match="30"):
        parse_items("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
                    "</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
    with pytest.raises(PublicFeedError):
        parse_items("<html>gateway timeout")
    with pytest.raises(PublicFeedError):
        NEMCClient("")


def test_client_pages_and_sends_region_params():
    seen = []

    def fetch(url, params):
        seen.append((url.rsplit("/", 1)[-1], dict(params)))
        page = params["pageNo"]
        item = f"<item><hpid>H{page}</hpid></item>" if page <= 2 else ""
        return (f"<response><header><resultCode>00</resultCode></header><body><items>{item}</items>"
                f"<totalCount>2</totalCount></body></response>")

    rows = NEMCClient("k", fetch=fetch, rows=1).beds("경기도", "고양시")
    assert [r["hpid"] for r in rows] == ["H1", "H2"]
    assert seen[0][0] == "getEmrrmRltmUsefulSckbdInfoInqire"
    assert seen[0][1]["STAGE1"] == "경기도" and seen[0][1]["STAGE2"] == "고양시" and seen[0][1]["serviceKey"] == "k"


def test_missing_coordinates_are_reported():
    now = datetime.now(KST)
    beds = [{"hpid": "A", "dutyName": "A병원", "hvidate": (now - timedelta(minutes=1)).strftime("%Y%m%d%H%M%S"),
             "hvec": "1"}, {"hpid": "B", "dutyName": "B병원", "hvec": "1"}]
    directory = [{"hpid": "A", "dutyName": "A병원", "wgs84Lat": "37.5", "wgs84Lon": "127.0"}]
    snap = build_network(directory, beds, [])
    assert [h.id for h in snap.hospitals] == ["A"] and snap.skipped == ["B병원: 좌표 없음"]
    with pytest.raises(PublicFeedError):
        build_network([], beds, [])
