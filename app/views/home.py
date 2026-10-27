import streamlit as st

from common import esc, header, tile

header("Human-supervised decision intelligence", "Overview")

st.markdown(
    '<div class="sh-hero"><div class="ghost">SYNAPSE-H</div>'
    '<span class="sh-eyebrow">Emergency transfer · hospital acceptance</span>'
    "<h1>응급 전원을 위한 사람 감독형 의사결정 지능</h1>"
    "<p>의뢰 데이터를 구조화하고, 목적지 준비도를 예측하며, 불확실성 아래에서 임상적으로 적합한 병원을 "
    "<b>설명 가능한 상위 3개 옵션</b>으로 제시합니다. 최종 결정 권한은 항상 의료진에게 있습니다.</p></div>",
    unsafe_allow_html=True)

st.markdown(
    '<div class="sh-why"><span class="sh-eyebrow">The one-sentence case</span>'
    "한국에는 실시간 응급자원 데이터가 있지만, 데이터 피드는 <i>어느 적합 병원이 이 환자를 제때 수용할 가능성이 "
    "가장 높은지</i> 결정해 주지 않습니다. Synapse-H는 파편화된 입력을 사람이 결정할 수 있는 세 개의 순위화된 "
    "설명 가능한 옵션으로 바꿉니다.</div>", unsafe_allow_html=True)
st.write("")

stats = [
    ("119 구급 출동 (2024)", "3.32M", "National Fire Agency [2]"),
    ("응급실 방문 (2024)", "7.84M", "NEMC 2024 통계 [3]"),
    ("지정 응급의료기관", "414", "권역 44 · 지역센터 137 · 지역기관 233"),
    ("급성기 병상 중 ICU", "4.1%", "12,023 / 290,361 병상 [6]"),
]
for c, (k, v, s) in zip(st.columns(4), stats):
    c.markdown(tile(k, v, s), unsafe_allow_html=True)

st.write("")
st.markdown('<span class="sh-eyebrow">Workflow</span>', unsafe_allow_html=True)
st.markdown("## 다섯 단계, 한 번의 사람 결정")
steps = [
    ("Capture", "의뢰서·활력징후·Pre-KTAS·필요 역량 입력"),
    ("Confirm", "언어 모델이 필드를 제안하고 의료진이 확인"),
    ("Match", "준비도 + 이동시간 + 수용 예측"),
    ("Decide", "Top 3 옵션·근거·불확실성 → 의료진 선택"),
    ("Learn", "수용·거절·오버라이드·시간 감사 기록"),
]
orbit = ('<svg viewBox="0 0 1000 90" preserveAspectRatio="none" aria-hidden="true">'
         '<path d="M90,44 C230,10 320,96 400,78 S610,8 700,44 S860,96 910,44" fill="none" '
         'stroke="#F37338" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>')
st.markdown(
    '<div class="sh-steps">' + orbit + "".join(
        f'<div class="sh-step"><div class="orb">{i}</div><div><b>{esc(t)}</b><small>{esc(d)}</small></div></div>'
        for i, (t, d) in enumerate(steps, 1)) + "</div>", unsafe_allow_html=True)
st.caption("피드백은 병원 준비도 예측과 워크플로를 개선할 뿐, 자율적 임상 권한을 갖지 않습니다.")

st.write("")
st.markdown('<span class="sh-eyebrow">Workspace</span>', unsafe_allow_html=True)
st.markdown("## 무엇을 할 수 있나요")
portraits = [
    ("orchestrator", "🚑", "Operations", "전원 오케스트레이터", "의뢰서 → 확인 → Top 3 → 결정 → 기록"),
    ("command", "🗺️", "Operations", "지역 상황실", "활성 케이스·피드 신선도·네트워크"),
    ("allocation", "🧮", "Operations", "다중 환자 동시 배정", "병상·공정성 제약 하 전역 최적 배정"),
    ("twin", "🧪", "Evidence", "합성 디지털 트윈", "Nearest vs Synapse-H 짝지은 시뮬레이션"),
    ("audit", "🛡️", "Governance", "감사 로그 · 안전", "추천·결정·오버라이드 추적, 모델 카드"),
    ("business", "📈", "Business", "시장 · 사업 모델", "TAM/SAM/SOM, 5개년 시나리오"),
]
st.markdown(
    '<div class="sh-orbits">' + "".join(
        f'<a class="sh-portrait" href="./{path}" target="_self"><div class="disc">{icon}'
        f'<span class="sat">→</span></div><span class="sh-eyebrow">{esc(cat)}</span>'
        f'<b>{esc(title)}</b><small>{esc(desc)}</small></a>'
        for path, icon, cat, title, desc in portraits) + "</div>", unsafe_allow_html=True)

st.write("")
st.markdown('<span class="sh-eyebrow">Product boundaries</span>', unsafe_allow_html=True)
st.markdown("## Non-goals are product requirements")
st.table({
    "Non-goal": ["자율 출동 없음", "검증되지 않은 자유텍스트 추론 없음", "생존 약속 없음",
                 "숨겨진 최적화 없음", "공개 병원 순위표 없음", "실제 환자 정보를 외부 LLM에 보내지 않음"],
    "설계 통제": ["권한 있는 사람이 목적지를 선택·확정", "추출 필드는 스키마·범위 검사 후 사람이 확인",
               "운영 준비도만 예측; 생존 모델은 별도 임상 검증 필요", "주요 요인·불확실성·오래된 입력·대안을 모두 표시",
               "운영 예측은 맥락·권한 제한, 평판 점수화 금지",
               "LLM 추출은 선택 사항·합성 메모 전용, 식별정보 형식이면 전송 차단 · 실제 운영은 승인된 사설/온프레미스 추론 환경만"],
})

st.markdown(
    '<div class="sh-footer"><h2>최종 결정은 언제나 사람이 내립니다.</h2><div class="cols">'
    '<div><div class="h">Safety boundary</div><p>Synapse-H는 자율적으로 출동 지시·진단·병상 배정을 하거나 '
    "생존을 약속하지 않습니다. 환자별 영향은 후향적 검증, Shadow mode 평가, 임상 승인, 식약처 분류 결정 이후에만 "
    "도입됩니다.</p></div>"
    '<div><div class="h">Data</div><p>기본 병원·환자 값은 가상 예시입니다. \'공공 데이터 연동\'을 켜면 병원 병상·역량은 '
    "국립중앙의료원 공공데이터를 쓰지만 수용률·응답 시간은 가정값입니다. 실제 환자 데이터는 쓰지 않으며 임상 검증을 "
    "거치지 않았습니다.</p></div>"
    '<div><div class="h">Source</div><p>Hyeonwoo An, SYNAPSE-H Business Proposal, International Youth '
    "Entrepreneurship Olympiad 2026 (University Division).</p></div></div>"
    '<div class="rule"></div><div class="fine">SYNAPSE-H · Human-supervised decision intelligence for emergency '
    "transfer and hospital acceptance</div></div>", unsafe_allow_html=True)
