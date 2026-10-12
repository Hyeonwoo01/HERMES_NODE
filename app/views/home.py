import streamlit as st

from common import SERIES, tile

st.markdown('<div class="sh-bar"><b>SYNAPSE-H &nbsp;|&nbsp; TRANSFER ORCHESTRATOR</b>'
            '<span>HUMAN-SUPERVISED DECISION INTELLIGENCE</span></div>', unsafe_allow_html=True)

st.markdown("## 응급 전원·병원 수용을 위한 사람 감독형 의사결정 지능")
st.markdown(
    "의뢰 데이터를 구조화하고, 목적지 준비도를 예측하며, 불확실성 아래에서 임상적으로 적합한 병원을 "
    "**설명 가능한 상위 3개 옵션**으로 제시합니다. **최종 결정 권한은 항상 의료진에게 있습니다.**"
)

st.info("**한 문장 요약** — 한국에는 실시간 응급자원 데이터가 있지만, 데이터 피드는 *어느 적합 병원이 "
        "이 환자를 제때 수용할 가능성이 가장 높은지* 결정해 주지 않습니다. Synapse-H는 파편화된 입력을 "
        "사람이 결정할 수 있는 세 개의 순위화된 설명 가능한 옵션으로 바꿉니다.")

cols = st.columns(4)
stats = [
    ("119 구급 출동 (2024)", "3.32M", "National Fire Agency [2]"),
    ("응급실 방문 (2024)", "7.84M", "NEMC 2024 통계 [3]"),
    ("지정 응급의료기관", "414", "권역 44 · 지역센터 137 · 지역기관 233"),
    ("급성기 병상 중 ICU 비중", "4.1%", "12,023 / 290,361 병상 [6]"),
]
for c, (k, v, s) in zip(cols, stats):
    c.markdown(tile(k, v, s), unsafe_allow_html=True)

st.markdown("### 다섯 단계 워크플로")
steps = [
    ("1 Capture", "의뢰서·활력징후·Pre-KTAS·필요 역량 입력", "#0b2545"),
    ("2 Confirm", "NLP가 FHIR 필드 제안 → 의료진 확인", SERIES[0]),
    ("3 Match", "준비도 + 이동시간 + 수용 예측", "#1f7a8c"),
    ("4 Decide", "Top 3 옵션·근거·불확실성 → 의료진 선택", "#0f7f6e"),
    ("5 Learn", "수용·거절·오버라이드·시간 감사 기록", "#1b8a5a"),
]
for c, (t, d, color) in zip(st.columns(5), steps):
    c.markdown(f'<div class="sh-step" style="background:{color}"><b>{t}</b><small>{d}</small></div>',
               unsafe_allow_html=True)
st.caption("피드백은 병원 준비도 예측과 워크플로를 개선할 뿐, 자율적 임상 권한을 갖지 않습니다.")

st.markdown("### 앱 구성")
left, right = st.columns(2)
with left:
    st.markdown("""
**운영 (Operations)**
- 🚑 **전원 오케스트레이터** — 의뢰서 입력 → 필드 확인 → Top 3 추천·근거 → 선택/오버라이드/의료지도 → 연락 결과 기록 → FHIR 번들
- 🗺️ **지역 상황실** — 활성 케이스, 1순위 수용률, 승인 시간 중앙값, 피드 신선도, 병원-케이스 네트워크
- 🧮 **다중 환자 동시 배정** — 병상 용량·부하 집중(공정성) 제약 하의 전역 최적 배정 vs 선착순 탐욕 배정
""")
with right:
    st.markdown("""
**검증·거버넌스 (Evidence)**
- 🧪 **합성 디지털 트윈** — Nearest-appropriate vs Synapse-H, 짝지은(paired) 에피소드 시뮬레이션과 민감도 분석
- 🛡️ **감사 로그 · 안전** — 추천·결정·오버라이드·연락 결과 추적, 파일럿 지표, 모델 카드, 위해 통제
- 📈 **시장 · 사업 모델** — Bottom-up TAM/SAM/SOM, 가격 가정, 5개년 기본 시나리오
""")

st.markdown("### 안전 경계 (Non-goals are product requirements)")
st.markdown(
    '<div class="sh-boundary"><b>Synapse-H는 자율적으로 출동 지시·진단·병상 배정을 하거나 생존을 약속하지 않습니다.</b> '
    "MVP는 의사결정 지원·조정 도구입니다. 환자별 영향은 후향적 검증, Shadow mode 평가, 임상 승인, "
    "식약처 분류 결정 이후에만 도입됩니다.</div>", unsafe_allow_html=True)

st.table({
    "Non-goal": ["자율 출동 없음", "검증되지 않은 자유텍스트 추론 없음", "생존 약속 없음",
                 "숨겨진 최적화 없음", "공개 병원 순위표 없음", "소비자용 LLM에 건강정보 없음"],
    "설계 통제": ["권한 있는 사람이 목적지를 선택·확정", "추출 필드는 스키마·범위 검사 후 사람이 확인",
               "운영 준비도만 예측; 생존 모델은 별도 임상 검증 필요", "주요 요인·불확실성·오래된 입력·대안을 모두 표시",
               "운영 예측은 맥락·권한 제한, 평판 점수화 금지", "승인된 사설/온프레미스 추론 환경만 허용"],
})
st.caption("출처: Hyeonwoo An, SYNAPSE-H Business Proposal (IYEO 2026). 앱의 모든 병원·환자 값은 가상 예시입니다.")
