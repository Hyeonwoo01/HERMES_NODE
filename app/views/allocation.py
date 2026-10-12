"""Concurrent multi-case allocation: global optimum vs first-come greedy."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import SERIES, hour, plotly_layout, tile
from synapse_h.capabilities import PATHWAYS
from synapse_h.intake import build_case
from synapse_h.optimizer import allocate, allocate_greedy

ss = st.session_state

st.markdown('<div class="sh-bar"><b>SYNAPSE-H &nbsp;|&nbsp; MULTI-CASE ALLOCATION</b>'
            '<span>CONCURRENT REGIONAL DEMAND</span></div>', unsafe_allow_html=True)
st.markdown(
    "한 환자에게 최선인 병원이 동시에 발생한 다른 환자에게 필요한 희소 자원을 소모할 수 있습니다 "
    "(제안서 §1.4 *Local optimization*). 동시 케이스는 병상 용량과 부하 집중(공정성) 벌점을 고려한 "
    "**할당 문제**로 풉니다. 임상 적격성(필수 역량)이 먼저 적용되고, 고위험(낮은 KTAS) 환자의 지연이 "
    "더 큰 비용으로 계산되어 고위험 환자를 불리하게 만들지 않습니다.")
st.latex(r"\min_x \sum_p \sum_h x_{ph}\,\alpha_p\,[w_1T_{ph}+w_2C_{h}+w_3(1-A_{h})R+w_4L_h+w_5U_h]"
         r" + \lambda F(x)")
st.caption("α_p: 중증도 가중치 (KTAS 1→1.6 … KTAS 5→0.7) · F(x) = Σ_h n_h(n_h−1)/2 (같은 병원 집중 벌점) · "
           "제약: 환자당 1개 목적지 또는 의료지도, 역량 충족, 병상 용량, 사람의 최종 확인")

st.markdown("#### 동시 대기 케이스 (의료진 확인 완료 · 도착 순)")
pw = list(PATHWAYS)
df = pd.DataFrame([{
    "case_id": c.case_id, "origin_id": c.origin_id, "pathway": c.pathway, "ktas": c.ktas, "age": c.age,
    "sex": c.sex, "onset_min": c.onset_min, "sbp": c.sbp, "hr": c.hr, "spo2": c.spo2,
} for c in ss.concurrent])
edited = st.data_editor(
    df, num_rows="dynamic", hide_index=True, use_container_width=True, key="cases_editor",
    column_config={
        "case_id": "케이스",
        "origin_id": st.column_config.SelectboxColumn("의뢰 기관", options=list(ss.origins), required=True),
        "pathway": st.column_config.SelectboxColumn("임상 경로", options=pw, required=True),
        "ktas": st.column_config.NumberColumn("KTAS", min_value=1, max_value=5, step=1, required=True),
        "age": st.column_config.NumberColumn("나이", min_value=0, max_value=110, step=1, required=True),
        "sex": st.column_config.SelectboxColumn("성별", options=["male", "female"], required=True),
        "onset_min": st.column_config.NumberColumn("경과(분)", min_value=0, required=True),
        "sbp": st.column_config.NumberColumn("SBP", required=True),
        "hr": st.column_config.NumberColumn("HR", required=True),
        "spo2": st.column_config.NumberColumn("SpO₂", required=True),
    },
)
cases, errors = [], []
for i, row in enumerate(edited.to_dict("records")):
    if any(pd.isna(v) for v in row.values()):
        continue
    try:
        cases.append(build_case(str(row["case_id"]) or f"N-{i}", row["origin_id"], row))
    except ValueError as e:
        errors.append(f"{row['case_id']}: {e}")
for e in errors:
    st.error(e)

lam = st.slider("공정성 벌점 λ (같은 병원으로의 부하 집중)", 0.0, 15.0, 3.0, 0.5)
if not cases:
    st.info("케이스를 한 개 이상 입력하세요.")
    st.stop()

g = allocate(cases, ss.network, ss.origins, ss.weights, lam, hour())
gr = allocate_greedy(cases, ss.network, ss.origins, ss.weights, lam, hour())
ESC_COST = 1e4


def clinical_cost(a):
    return a.total_cost - a.escalations * ESC_COST


c = st.columns(4)
c[0].markdown(tile("전역 최적 총비용", f"{clinical_cost(g):.1f}", "중증도 가중 + 공정성", "#0f7f6e"),
              unsafe_allow_html=True)
c[1].markdown(tile("선착순 탐욕 총비용", f"{clinical_cost(gr):.1f}", "도착 순으로 각자 최선 선택", SERIES[1]),
              unsafe_allow_html=True)
saving = clinical_cost(gr) - clinical_cost(g)
c[2].markdown(tile("네트워크 비용 절감", f"{saving:+.1f}" if g.escalations == gr.escalations else "—",
                   "탐욕 대비 (같은 에스컬레이션 수일 때)", "#0f7f6e"), unsafe_allow_html=True)
c[3].markdown(tile("의료지도 에스컬레이션", f"{g.escalations} / {gr.escalations}", "전역 / 탐욕",
                   "#b4541a" if g.escalations else "#0f7f6e"), unsafe_allow_html=True)
st.write("")

rows = []
for a, b in zip(g.assignments, gr.assignments):
    rows.append({
        "케이스": a.case.case_id, "경로": PATHWAYS[a.case.pathway].label.split(" (")[0], "KTAS": a.case.ktas,
        "전역 최적 배정": a.hospital.name if a.hospital else "🚨 의료지도",
        "개인 순위": a.individual_rank or "—", "ETA(분)": round(a.travel_min, 1) if a.travel_min else "—",
        "탐욕 배정": b.hospital.name if b.hospital else "🚨 의료지도",
        "탐욕 개인 순위": b.individual_rank or "—",
        "변경": "↔" if (a.hospital and b.hospital and a.hospital.id != b.hospital.id) or
                     (bool(a.hospital) != bool(b.hospital)) else "",
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
st.caption("개인 순위 = 그 환자 혼자였다면 매겨졌을 순위. 전역 최적화는 일부 저위험 환자에게 2순위를 배정해 "
           "고위험 환자의 1순위를 지킬 수 있습니다. 모든 배정은 의료진 확인 전까지 '제안'입니다.")

# Load per hospital, both methods.
names = [h.name for h in ss.network]
cnt_g = [sum(1 for a in g.assignments if a.hospital and a.hospital.id == h.id) for h in ss.network]
cnt_r = [sum(1 for a in gr.assignments if a.hospital and a.hospital.id == h.id) for h in ss.network]
beds = [h.beds_available for h in ss.network]
fig = go.Figure()
fig.add_bar(x=names, y=cnt_g, name="전역 최적", marker_color=SERIES[0], marker_line=dict(color="#fcfcfb", width=2),
            hovertemplate="%{x}<br>전역 최적: %{y}명<extra></extra>")
fig.add_bar(x=names, y=cnt_r, name="선착순 탐욕", marker_color=SERIES[1], marker_line=dict(color="#fcfcfb", width=2),
            hovertemplate="%{x}<br>탐욕: %{y}명<extra></extra>")
fig.add_scatter(x=names, y=beds, mode="markers", name="가용 병상", marker=dict(symbol="line-ew-open", size=28,
                color="#52514e", line=dict(width=2)), hovertemplate="%{x}<br>가용 병상 %{y}<extra></extra>")
fig.update_layout(barmode="group", yaxis_title="배정 환자 수", title="병원별 배정 (용량 대비)")
st.plotly_chart(plotly_layout(fig, height=360), use_container_width=True)

if st.button("💾 편집한 케이스 목록 저장 (지역 상황실에 반영)"):
    ss.concurrent = cases
    st.success(f"{len(cases)}개 케이스를 저장했습니다.")
