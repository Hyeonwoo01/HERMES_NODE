"""Synthetic digital twin: Nearest-appropriate vs Synapse-H over paired episodes."""

from dataclasses import replace

import plotly.graph_objects as go
import streamlit as st

from common import SERIES, plotly_layout
from synapse_h.twin import (SENSITIVITY_VARIABLES, TRAVEL_SURFACES, TwinParams,
                            sensitivity, simulate)

st.markdown('<div class="sh-bar"><b>SYNAPSE-H &nbsp;|&nbsp; SYNTHETIC DIGITAL TWIN</b>'
            '<span>NO PATIENT DATA · NOT CLINICAL VALIDATION</span></div>', unsafe_allow_html=True)
st.markdown(
    "**검증 질문:** 수용이 불확실하고 병원 역량이 이질적일 때, 이동 시간과 예측 수용 확률을 결합한 점수가 "
    "*가장 가까운 적합 병원*을 고르는 방식보다 순차 전화 탐색을 줄이는가? "
    "두 정책은 병원별 **동일한 잠재 수용 난수**를 공유하므로 차이는 연락 순서에서만 발생합니다.")

with st.expander("🔧 시나리오 파라미터", expanded=False):
    d = TwinParams()
    c1, c2, c3 = st.columns(3)
    n = c1.select_slider("에피소드 수", [2000, 5000, 10000, 20000, 50000], d.n_episodes)
    seed = c1.number_input("Random seed", value=d.seed, step=1)
    noise = c2.slider("예측 오차 (logit SD)", 0.0, 3.0, d.prediction_noise, 0.1)
    stale = c2.slider("피드 지연 확률", 0.0, 0.8, d.stale_prob, 0.05)
    surface = c3.selectbox("이동 표면", list(TRAVEL_SURFACES), index=0)
    cong = c3.slider("지역 혼잡도 (평균 shock)", -1.0, 2.0, d.congestion_mean, 0.1)
    c1, c2, c3 = st.columns(3)
    first = c1.slider("첫 연락 시간 (분)", 1.0, 6.0, d.first_contact_min, 0.5)
    failed = c2.slider("실패 연락당 추가 시간 (분)", 3.0, 12.0, d.failed_contact_min, 0.5)
    retry = c3.slider("정책의 거절 페널티 R (분)", 0.0, 30.0, d.retry_penalty_min, 1.0)
    params = replace(d, n_episodes=n, seed=int(seed), prediction_noise=noise, stale_prob=stale,
                     travel_surface=surface, congestion_mean=cong, first_contact_min=first,
                     failed_contact_min=failed, retry_penalty_min=retry)


@st.cache_data(show_spinner="시뮬레이션 실행 중…")
def run(p: TwinParams):
    r = simulate(p)
    return r.summary, r.episodes


summary, episodes = run(params)

st.markdown(f"#### 결과 — {params.n_episodes:,} paired episodes · 8개 병원 · 5개 질환군")


def fmt(v, kind, metric):
    if kind == "pct":
        return f"{v * 100:.1f}%"
    return f"{v:.2f}" if metric == "attempts" else f"{v:.1f}"


table = summary.copy()
for col in ("Nearest appropriate", "Synapse-H"):
    table[col] = [fmt(v, k, m) for v, k, m in zip(summary[col], summary["kind"], summary["metric"])]
st.dataframe(table[["지표", "Nearest appropriate", "Synapse-H", "Paired change"]],
             hide_index=True, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    s = summary.set_index("metric")
    keys = ["confirmation", "travel", "conf_plus_travel"]
    labels = ["승인 시간", "이송 시간", "승인+이송"]
    fig = go.Figure()
    for name, col, color in (("Nearest appropriate", "Nearest appropriate", SERIES[1]),
                             ("Synapse-H", "Synapse-H", SERIES[0])):
        fig.add_bar(x=labels, y=[s.loc[k, col] for k in keys], name=name, marker_color=color,
                    marker_line=dict(color="#fcfcfb", width=2),
                    hovertemplate=f"{name}<br>%{{x}}: %{{y:.1f}}분<extra></extra>")
    fig.update_layout(barmode="group", title="평균 시간 (분)", yaxis_title="분")
    st.plotly_chart(plotly_layout(fig, height=340), use_container_width=True)
with c2:
    fig = go.Figure()
    for name, col, color in (("Nearest appropriate", "nearest_attempts", SERIES[1]),
                             ("Synapse-H", "synapse_attempts", SERIES[0])):
        counts = episodes[col].value_counts(normalize=True).sort_index()
        counts = counts[counts.index <= 5]
        fig.add_bar(x=[str(int(i)) for i in counts.index], y=counts.values * 100, name=name, marker_color=color,
                    marker_line=dict(color="#fcfcfb", width=2),
                    hovertemplate=f"{name}<br>연락 %{{x}}회: %{{y:.1f}}%<extra></extra>")
    fig.update_layout(barmode="group", title="연락 횟수 분포", xaxis_title="연락 횟수", yaxis_title="에피소드 %")
    st.plotly_chart(plotly_layout(fig, height=340), use_container_width=True)

st.markdown("#### 질환군별 1순위 수용률")
by = episodes.groupby("condition")[["nearest_first_accept", "synapse_first_accept"]].mean() * 100
fig = go.Figure()
fig.add_bar(x=by.index, y=by["nearest_first_accept"], name="Nearest appropriate", marker_color=SERIES[1],
            marker_line=dict(color="#fcfcfb", width=2), hovertemplate="%{x}: %{y:.1f}%<extra>Nearest</extra>")
fig.add_bar(x=by.index, y=by["synapse_first_accept"], name="Synapse-H", marker_color=SERIES[0],
            marker_line=dict(color="#fcfcfb", width=2), hovertemplate="%{x}: %{y:.1f}%<extra>Synapse-H</extra>")
fig.update_layout(barmode="group", yaxis_title="1순위 수용률 (%)")
st.plotly_chart(plotly_layout(fig, height=320), use_container_width=True)
st.caption("소아 경로는 적격 병원이 2곳뿐이라 개선 여지가 작습니다 — 역량 희소성은 최적화로 해결되지 않습니다.")

st.markdown("#### 민감도 분석 (부록 A.2)")
var = st.selectbox("변수", list(SENSITIVITY_VARIABLES), format_func=lambda k: SENSITIVITY_VARIABLES[k][0])


@st.cache_data(show_spinner="민감도 분석 중…")
def sweep(v: str, base: TwinParams):
    return sensitivity(v, base)


sens = sweep(var, params)
fig = go.Figure()
xs = [str(v) for v in sens[var]]
fig.add_scatter(x=xs, y=sens["first_accept_gain_pp"], mode="lines+markers", name="1순위 수용률 개선 (%p)",
                line=dict(color=SERIES[0], width=2), marker=dict(size=9))
fig.add_hline(y=0, line_color="#c3c2b7")
fig.update_layout(title="Synapse-H − Nearest: 1순위 수용률 차이 (%p)", xaxis_title=SENSITIVITY_VARIABLES[var][0])
st.plotly_chart(plotly_layout(fig, height=300), use_container_width=True)
sens_show = sens.rename(columns={var: SENSITIVITY_VARIABLES[var][0],
                                 "first_accept_gain_pp": "1순위 수용 개선(%p)",
                                 "confirmation_change_min": "승인 시간 변화(분)",
                                 "travel_change_min": "이송 시간 변화(분)",
                                 "total_change_min": "승인+이송 변화(분)"})
st.dataframe(sens_show.round(2), hide_index=True, use_container_width=True)
st.caption("예측 오차가 커질수록 이득은 완만하게 감소해야 합니다. 이득이 0 이하로 떨어지는 영역에서는 "
           "abstention이 증가해야 하며 제품 결정에 사용하면 안 됩니다.")

st.download_button("에피소드 단위 결과 다운로드 (.csv)", episodes.to_csv(index=False),
                   file_name=f"digital_twin_seed{params.seed}.csv", mime="text/csv")

st.markdown(
    '<div class="sh-boundary"><b>해석 방법</b> — 이 시뮬레이션은 계산적 타당성을 보여주고 파일럿 목표 설정에 '
    "참고할 뿐입니다. 사망률 추정, 임상적 안전성 입증, 한국 병원 행태 재현, 예측 모델 검증이 아닙니다. "
    "가정은 모두 공개되어 있고(<code>synapse_h/twin.py</code>) 파트너 데이터로 하나씩 교체할 수 있습니다. "
    "‘위험보정 지연 지표’는 양식화된 지표이며 사망률이 아닙니다.</div>", unsafe_allow_html=True)
st.caption(f"제안서 Table 9 참고값 (창업자 원 트윈): 1순위 수용 62.3% → 70.9%, 평균 승인 6.6 → 5.6분, "
           f"평균 이송 13.6 → 14.1분. 본 앱의 트윈은 독립 구현이므로 수치가 다를 수 있습니다. "
           f"seed={params.seed}, 재현 가능.")
