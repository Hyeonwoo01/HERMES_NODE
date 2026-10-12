"""Regional command view: operational state, feed health and active transfers."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import INK2, MUTED, SERIES, STATUS, esc, hour, plotly_layout, tile
from synapse_h.data import REGION_NAME
from synapse_h.models import CAPABILITY_LABELS
from synapse_h.optimizer import allocate
from synapse_h.readiness import STALE_THRESHOLD_MIN, UNVERIFIABLE_MIN, predict_readiness

ss = st.session_state
ss.setdefault("transfers", [])

st.markdown(f'<div class="sh-bar"><b>SYNAPSE-H &nbsp;|&nbsp; REGIONAL COMMAND VIEW</b>'
            f'<span>{esc(REGION_NAME.upper())} • {ss.clock:%H:%M}</span></div>', unsafe_allow_html=True)

net = ss.network
plan = allocate(ss.concurrent, net, ss.origins, ss.weights, hour=hour())
m = ss.audit.metrics()
stale = [h for h in net if h.feed_age_min > STALE_THRESHOLD_MIN]
active = len(ss.concurrent) + sum(t["status"] != "수용" for t in ss.transfers)

fca = m["first_choice_accept"]
med = m["median_confirmation_min"]
cols = st.columns(4)
cols[0].markdown(tile("Active cases", str(active), "동시 대기 + 진행 중 케이스", SERIES[0]), unsafe_allow_html=True)
cols[1].markdown(tile("First-choice accept", f"{fca:.0%}" if fca is not None else "—",
                      "오케스트레이터 연락 기록 기준", "#0f7f6e"), unsafe_allow_html=True)
cols[2].markdown(tile("Median confirmation", f"{med:.1f}m" if med is not None else "—",
                      "첫 연락 3분 + 실패당 6분", "#0f7f6e"), unsafe_allow_html=True)
cols[3].markdown(tile("Stale feeds", str(len(stale)), f"{STALE_THRESHOLD_MIN:.0f}분 신선도 임계값 초과",
                      "#b4541a" if stale else "#0f7f6e"), unsafe_allow_html=True)
st.write("")

left, right = st.columns([3, 2])
with left:
    st.markdown("**LIVE REGIONAL NETWORK**")
    fig = go.Figure()
    # Edges first so nodes sit on top.
    hosp = {h.id: h for h in net}
    edge_x, edge_y, edge_x2, edge_y2 = [], [], [], []
    for a in plan.assignments:
        if a.hospital:
            o = ss.origins[a.case.origin_id]
            edge_x += [o.x, a.hospital.x, None]
            edge_y += [o.y, a.hospital.y, None]
    for t in ss.transfers:
        if t["hospital"]:
            o, h = ss.origins[t["origin"]], hosp[t["hospital"]]
            edge_x2 += [o.x, h.x, None]
            edge_y2 += [o.y, h.y, None]
    fig.add_scatter(x=edge_x, y=edge_y, mode="lines", line=dict(color="#c3c2b7", width=2, dash="dot"),
                    name="계획 배정 (동시 대기 케이스)", hoverinfo="skip")
    fig.add_scatter(x=edge_x2, y=edge_y2, mode="lines", line=dict(color=SERIES[0], width=2),
                    name="확정 전원", hoverinfo="skip")
    status_color = [STATUS["serious"] if h.feed_age_min > STALE_THRESHOLD_MIN else "#0f7f6e" for h in net]
    fig.add_scatter(
        x=[h.x for h in net], y=[h.y for h in net], mode="markers+text", text=[h.id for h in net],
        textposition="top center", marker=dict(size=20, color=status_color, line=dict(color="#fcfcfb", width=2)),
        name="병원 (주황 = 피드 지연)",
        customdata=[[h.name, h.tier, h.beds_available, f"{h.load:.0%}", h.feed_age_min] for h in net],
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>가용 병상 %{customdata[2]} · "
                      "부하 %{customdata[3]}<br>피드 %{customdata[4]:.0f}분 전<extra></extra>",
    )
    org = list(ss.origins.values())
    fig.add_scatter(x=[o.x for o in org], y=[o.y for o in org], mode="markers+text",
                    text=[o.id for o in org], textposition="bottom center",
                    marker=dict(size=14, color=SERIES[4], symbol="diamond", line=dict(color="#fcfcfb", width=2)),
                    name="의뢰 기관", customdata=[o.name for o in org],
                    hovertemplate="%{customdata}<extra></extra>")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x")
    st.plotly_chart(plotly_layout(fig, height=420), use_container_width=True)

with right:
    st.markdown("**CAPABILITY & FEED HEALTH**")
    for h in net:
        r = predict_readiness(h, hour())
        state = ("critical", "⛔ 제외") if h.feed_age_min > UNVERIFIABLE_MIN else \
            ("serious", "⚠ 지연") if r.stale else ("good", "✓ 신선")
        pct = min(100, h.feed_age_min / UNVERIFIABLE_MIN * 100)
        caps = " · ".join(CAPABILITY_LABELS[c] for c in sorted(h.capabilities) if c != "CT")[:46]
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:6px 0">'
            f'<b style="width:26px">{h.id}</b>'
            f'<span style="width:150px;font-size:.78rem;color:{INK2};overflow:hidden;white-space:nowrap;'
            f'text-overflow:ellipsis" title="{esc(caps)}">{esc(h.tier)}</span>'
            f'<span style="flex:1;background:#eceae4;height:8px;border-radius:4px;position:relative">'
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:{max(4, pct):.0f}%;'
            f'background:{STATUS[state[0]]};border-radius:4px"></span></span>'
            f'<span style="width:44px;text-align:right;font-size:.8rem">{h.feed_age_min:.0f}m</span>'
            f'<span style="width:58px;font-size:.75rem;color:{MUTED}">{state[1]}</span></div>',
            unsafe_allow_html=True)
    st.caption(f"막대 = 마지막 갱신 후 경과 (가득 = {UNVERIFIABLE_MIN:.0f}분, 제외 기준)")

if stale:
    st.warning(f"**ALERT** {', '.join(h.id for h in stale)} 피드가 {STALE_THRESHOLD_MIN:.0f}분 신선도 임계값을 "
               "초과했습니다. 해당 병원 추천은 하향 가중되며 화면에 표시됩니다.")

c1, c2, c3 = st.columns(3)
if c1.button("⏩ 시간 경과 시뮬레이션 (+10분)", use_container_width=True):
    for h in net:
        h.feed_age_min += 10
    st.rerun()
if c2.button("🔄 모든 피드 갱신", use_container_width=True):
    for h in net:
        h.feed_age_min = 1
    st.rerun()
if c3.button("↺ 네트워크 초기화", use_container_width=True):
    from synapse_h.data import default_network
    ss.network = default_network()
    ss.transfers = []
    st.rerun()

st.markdown("#### 병원 운영 상태 (역할 제한 · 공개 순위표 아님)")
st.caption("값을 직접 수정해 병상·부하·피드 지연 변화를 시뮬레이션할 수 있습니다. 모든 화면에 즉시 반영됩니다.")
df = pd.DataFrame([{
    "ID": h.id, "병원": h.name, "등급": h.tier, "가용 병상": h.beds_available, "부하": h.load,
    "과거 수용률": h.hist_accept_rate, "승인 지연(분)": h.confirm_delay_min, "피드 경과(분)": h.feed_age_min,
    "예측 수용": round(predict_readiness(h, hour()).accept_prob, 2),
} for h in net])
edited = st.data_editor(
    df, hide_index=True, use_container_width=True,
    disabled=["ID", "병원", "등급", "예측 수용"],
    column_config={
        "부하": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
        "과거 수용률": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
        "가용 병상": st.column_config.NumberColumn(min_value=0, max_value=20, step=1),
        "피드 경과(분)": st.column_config.NumberColumn(min_value=0, max_value=600, step=1),
    },
)
changed = False
for h, row in zip(net, edited.to_dict("records")):
    new = (int(row["가용 병상"]), float(row["부하"]), float(row["과거 수용률"]),
           float(row["승인 지연(분)"]), float(row["피드 경과(분)"]))
    if new != (h.beds_available, h.load, h.hist_accept_rate, h.confirm_delay_min, h.feed_age_min):
        (h.beds_available, h.load, h.hist_accept_rate, h.confirm_delay_min, h.feed_age_min) = new
        changed = True
if changed:
    st.rerun()

if ss.transfers:
    st.markdown("#### 오케스트레이터 전원 기록")
    st.dataframe(pd.DataFrame([{
        "케이스": t["case_id"], "의뢰 기관": ss.origins[t["origin"]].name,
        "목적지": next((h.name for h in net if h.id == t["hospital"]), "의료지도"), "상태": t["status"],
    } for t in ss.transfers]), hide_index=True, use_container_width=True)
