"""Market sizing and illustrative base case (all prices are management assumptions)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import SERIES, header, plotly_layout, tile

header("Market & Business Model · 시장·사업 모델", "Planning assumptions")
st.caption("기관 수: NEMC 2024 통계 [3]. 가격·예측은 경영진 가정이며 계약을 의미하지 않습니다. "
           "슬라이더로 가정을 바꿔 보세요.")

st.markdown("#### Bottom-up 한국 반복 매출 시장")
c1, c2, c3 = st.columns(3)
p_cmd = c1.number_input("Regional command (₩M/년)", value=250, step=10)
p_adv = c2.number_input("Advanced center node (₩M/년)", value=60, step=5)
p_ess = c3.number_input("Essential institution node (₩M/년)", value=24, step=2)

units = {
    "TAM": (17, 181, 233),
    "SAM (5개 권역)": (5, 45, 60),
    "SOM (3년차)": (2, 15, 10),
}
rows = []
for k, (a, b, c) in units.items():
    rows.append({"구분": k, "지역 지휘": a, "고급 노드": b, "기본 노드": c,
                 "연간 가치 (₩B)": (a * p_cmd + b * p_adv + c * p_ess) / 1000})
df = pd.DataFrame(rows)
cols = st.columns(3)
for col, r, color in zip(cols, rows, SERIES):
    col.markdown(tile(r["구분"], f"₩{r['연간 가치 (₩B)']:.2f}B",
                      f"{r['지역 지휘']} 지역 · {r['고급 노드']} 고급 · {r['기본 노드']} 기본"),
                 unsafe_allow_html=True)
st.write("")
st.dataframe(df.round(2), hide_index=True, width="stretch")
st.caption("TAM = 17개 광역 지자체 × 지휘 라이선스 + 181개 권역·지역센터 × 고급 노드 + 233개 지역기관 × 기본 노드. "
           "일회성 통합·컨설팅·성과 기반 수수료·해외 매출 제외.")

st.markdown("#### 가격 구조")
st.dataframe(pd.DataFrame([
    ["유료 진단 / 준비도 평가", "지역 또는 병원 네트워크", "₩20–40M 일회성", "워크플로 맵, 데이터 인벤토리, 보안·규제 갭, 파일럿 프로토콜"],
    ["Shadow-mode 파일럿", "지역 + 병원 3–5곳", "₩100–150M / 6–9개월", "통합, 교육, shadow 추천, 평가"],
    ["Essential node", "지역응급의료기관", "₩24M / 년", "구조화 인테이크, 케이스 교환, 기본 분석"],
    ["Advanced node", "권역/지역 응급의료센터", "₩60M / 년", "전체 오케스트레이션, 준비도 모델, 고급 SLA"],
    ["Regional command", "지자체 / 상황실", "₩250M / 년", "지역 최적화, 거버넌스, 시스템 KPI"],
    ["통합 패키지", "병원", "₩15M 일회성", "EMR/FHIR/API 어댑터, 인터페이스 검증"],
], columns=["상품", "구매자", "계획 가격", "포함 가치"]), hide_index=True, width="stretch")

st.markdown("#### 5개년 기본 시나리오 (예시)")
scale = st.slider("판매 도입 속도 (기본 대비)", 0.4, 1.4, 1.0, 0.05,
                  help="0.65 ≈ 제안서의 하방 시나리오 (손익분기 4년차로 이동)")
base = pd.DataFrame({
    "연도": ["Y1", "Y2", "Y3", "Y4", "Y5"],
    "매출": [0.15, 0.72, 1.95, 4.75, 9.20],
    "COGS": [0.05, 0.18, 0.45, 1.00, 1.84],
    "운영비": [0.34, 0.72, 1.28, 2.48, 4.22],
})
base["매출"] *= scale
base["COGS"] *= scale
base["EBITDA"] = base["매출"] - base["COGS"] - base["운영비"]
be = next((y for y, e in zip(base["연도"], base["EBITDA"]) if e > 0), "5년 내 없음")

fig = go.Figure()
fig.add_bar(x=base["연도"], y=base["매출"], name="매출", marker_color=SERIES[0],
            marker_line=dict(color="#F3F0EE", width=2), hovertemplate="%{x} 매출 ₩%{y:.2f}B<extra></extra>")
fig.add_bar(x=base["연도"], y=base["COGS"] + base["운영비"], name="COGS + 운영비", marker_color=SERIES[1],
            marker_line=dict(color="#F3F0EE", width=2), hovertemplate="%{x} 비용 ₩%{y:.2f}B<extra></extra>")
fig.add_scatter(x=base["연도"], y=base["EBITDA"], name="EBITDA", mode="lines+markers",
                line=dict(color=SERIES[2], width=2), marker=dict(size=9),
                hovertemplate="%{x} EBITDA ₩%{y:.2f}B<extra></extra>")
fig.add_hline(y=0, line_color="#D1CDC7")
fig.update_layout(barmode="group", yaxis_title="₩ Billion", title=f"영업 손익분기: {be}")
st.plotly_chart(plotly_layout(fig, height=360), width="stretch",
                config={"displayModeBar": False})
st.dataframe(base.round(2), hide_index=True, width="stretch")
st.caption("운영비는 고정으로 두고 매출·COGS만 도입 속도에 비례시킨 단순 모델입니다. 자금조달·세금·운전자본 제외.")

st.markdown("#### 12개월 ₩70M 사용 계획")
funds = pd.DataFrame({
    "항목": ["코어 제품·최적화", "보안·FHIR 통합", "임상 검증·규제", "클라우드·모델 운영", "파일럿 UX·교육", "법무·보험·예비비"],
    "금액(₩M)": [20, 15, 12, 8, 8, 7],
})
fig = go.Figure(go.Bar(x=funds["금액(₩M)"], y=funds["항목"], orientation="h", marker_color=SERIES[0],
                       hovertemplate="%{y}: ₩%{x}M<extra></extra>", text=funds["금액(₩M)"].map(lambda v: f"₩{v}M"),
                       textposition="outside"))
fig.update_yaxes(autorange="reversed")
st.plotly_chart(plotly_layout(fig, height=300), width="stretch",
                config={"displayModeBar": False})
