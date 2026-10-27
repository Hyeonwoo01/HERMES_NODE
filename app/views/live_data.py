"""Load a region's emergency departments from the public NEMC API into the ranking engine."""

import pandas as pd
import streamlit as st

from common import can, denied, header, secrets
from synapse_h.data import default_network, origins
from synapse_h.models import CAPABILITY_LABELS
from synapse_h.public_feed import (ASSUMPTIONS, NOT_IN_API, NEMCClient, PublicFeedError, load_region,
                                   sample_client)

ss = st.session_state
SIDO = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
        "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
        "경상북도", "경상남도", "제주특별자치도"]

header("Public Data · 공공 응급의료 데이터 연동", "국립중앙의료원 OpenAPI")
st.markdown(
    "공공데이터포털의 **국립중앙의료원 전국 응급의료기관 정보 조회 서비스**에서 응급실 가용 병상, CT·MRI 가용 여부, "
    "중증질환 수용 가능 정보, 좌표를 불러와 추천 엔진의 병원 목록으로 씁니다.")
with st.expander("공공데이터에 없는 값과 처리 방법"):
    st.markdown("\n".join(f"- {a}" for a in ASSUMPTIONS))
    st.markdown("- '정보미제공'이거나 빈 역량은 **없는 것으로** 처리합니다. 데이터가 비어서 병원이 후보가 되는 일은 없습니다.\n"
                "- 이 API에 없는 역량: " + ", ".join(NOT_IN_API.values()) +
                " → 배포 Secrets의 지역 지정 목록(`TRAUMA_CENTERS`, `PICU_HOSPITALS`)으로만 추가합니다.\n"
                "- 60분 넘게 갱신되지 않은 병원은 추천에서 제외됩니다.")

if not can("load_live_data"):
    denied("공공 데이터 불러오기")
    st.stop()

cfg = secrets()
key = str(cfg.get("DATA_GO_KR_SERVICE_KEY", "")).strip()
overrides: dict[str, set[str]] = {}
for name, cap in (("TRAUMA_CENTERS", "trauma_surgery"), ("PICU_HOSPITALS", "PICU")):
    for hpid in cfg.get(name, []) or []:
        overrides.setdefault(str(hpid), set()).add(cap)

c1, c2 = st.columns(2)
sido = c1.selectbox("시도", SIDO, index=SIDO.index("경기도"))
sigungu = c2.text_input("시군구 (선택, 예: 고양시)")


@st.cache_data(ttl=60, show_spinner="공공데이터를 불러오는 중…")
def fetch(service_key: str, sido: str, sigungu: str, overrides_items: tuple):
    return load_region(NEMCClient(service_key), sido, sigungu, capability_overrides=dict(overrides_items))


b1, b2 = st.columns(2)
snap, label = None, ""
if key:
    if b1.button("🔄 실시간 데이터 불러오기", type="primary", width="stretch"):
        try:
            ss.live_snapshot = fetch(key, sido, sigungu.strip(), tuple(sorted((k, frozenset(v)) for k, v in overrides.items())))
            ss.live_kind = "live"
        except (PublicFeedError, OSError) as e:
            st.error(f"불러오지 못했습니다: {e}")
else:
    b1.info("서비스 키가 설정되지 않았습니다. data.go.kr에서 활용 신청 후 배포 Secrets에 "
            "`DATA_GO_KR_SERVICE_KEY`(Decoding 키)를 넣으면 실시간 데이터를 불러옵니다.")
if b2.button("🧪 샘플 응답으로 미리보기 (합성)", width="stretch"):
    ss.live_snapshot = load_region(sample_client(), sido)
    ss.live_kind = "sample"

snap = ss.get("live_snapshot")
if snap is not None:
    kind = ss.get("live_kind")
    st.caption(("합성 샘플 응답 (공공데이터 형식, 가상 병원)" if kind == "sample" else snap.source)
               + f" · 불러온 시각 {snap.fetched_at:%H:%M:%S} UTC · 병원 {len(snap.hospitals)}곳")
    st.dataframe(pd.DataFrame([{
        "병원": h.name, "등급": h.tier, "응급실 가용": h.beds_available, "부하(추정)": f"{h.load:.0%}",
        "갱신(분 전)": round(h.feed_age_min), "역량": ", ".join(CAPABILITY_LABELS[c] for c in sorted(h.capabilities)),
        "정보미제공": ", ".join(snap.unknown.get(h.id, [])),
    } for h in snap.hospitals]), hide_index=True, width="stretch")
    if snap.skipped:
        st.caption("제외: " + "; ".join(snap.skipped))
    c1, c2 = st.columns(2)
    if c1.button("✅ 이 병원 목록으로 추천하기", type="primary", width="stretch"):
        ss.network, ss.origins = snap.hospitals, snap.origins
        ss.data_source = "live" if kind == "live" else "sample"
        ss.orch = {"stage": "capture"}
        st.success("전원 오케스트레이터가 이 병원 목록을 씁니다. 의뢰 기관도 이 지역 목록에서 고르세요.")
    if c2.button("↩ 합성 네트워크로 되돌리기", width="stretch"):
        ss.network, ss.origins, ss.data_source = default_network(), origins(), "synthetic"
        ss.orch = {"stage": "capture"}
        st.rerun()

st.caption(f"현재 추천에 쓰는 병원 목록: **{ {'synthetic': '합성 네트워크', 'sample': '합성 샘플 응답', 'live': '공공데이터 실시간'}[ss.data_source] }**")
