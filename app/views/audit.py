"""Safety & Audit: trace, pilot metrics, model card and hazard controls."""

import json

import pandas as pd
import streamlit as st

from common import auth_enabled, can, header, tile
from synapse_h.models import MODEL_VERSION
from synapse_h.readiness import COEF, STALE_THRESHOLD_MIN, UNVERIFIABLE_MIN

ss = st.session_state

header("Safety & Audit · 감사 로그", "Reviewable trace")

m = ss.audit.metrics()


def pct(v):
    return "—" if v is None else f"{v:.0%}"


def num(v, fmt="{:.2f}", unit=""):
    return "—" if v is None else fmt.format(v) + unit


c = st.columns(4)
c[0].markdown(tile("기록된 케이스", str(m["cases"]), f"연락 {m['contacted_cases']} · 미해결 {m['unresolved_cases']}"),
              unsafe_allow_html=True)
c[1].markdown(tile("오버라이드율", pct(m["override_rate"]), f"결정 {m['decisions']}건 · 사유 100% 기록"),
              unsafe_allow_html=True)
c[2].markdown(tile("첫 통화 수용률", pct(m["first_contact_accept"]), "어느 순위든 처음 연락한 병원"),
              unsafe_allow_html=True)
c[3].markdown(tile("모델 1순위 수용률", pct(m["model_top1_accept"]),
                   f"1순위에 먼저 연락한 {m['model_top1_cases']}건 기준"), unsafe_allow_html=True)
st.write("")
c = st.columns(4)
c[0].markdown(tile("케이스당 연락", num(m["mean_contacts"]), "미해결 케이스 포함"), unsafe_allow_html=True)
c[1].markdown(tile("수용까지 실제 경과", num(m["median_measured_min"], "{:.1f}", "분"),
                   "중앙값 · 이 데모의 기록 시각 기준"), unsafe_allow_html=True)
c[2].markdown(tile("가정 기준 승인 시간", num(m["median_assumed_min"], "{:.0f}", "분"),
                   "첫 연락 3분 + 실패당 6분 (측정값 아님)"), unsafe_allow_html=True)
c[3].markdown(tile("에스컬레이션", str(m["escalations"]), "의료지도 호출/권고 케이스"), unsafe_allow_html=True)
st.write("")

store = ss.audit.store
if store is None:
    st.caption("저장 방식: 이 브라우저 세션 메모리 (공개 데모). 배포 Secrets에 `AUDIT_DB_PATH`를 지정하면 "
               "수정·삭제가 막힌 SQLite 파일에 해시 체인으로 저장됩니다.")
else:
    problems = store.verify()
    if problems:
        st.error("감사 로그 무결성 검사 실패: " + "; ".join(problems[:5]))
    else:
        st.caption(f"저장 방식: 추가만 가능한 SQLite (`{store.path}`) · 해시 체인 검사 통과 · 이벤트 {len(ss.audit.events)}건")
st.caption("로그인: " + ("계정·역할 사용 중" if auth_enabled() else "미설정 (공개 데모 — 누구나 모든 기능 사용)"))

tab_log, tab_pilot, tab_card, tab_hazard = st.tabs(["감사 로그", "파일럿 목표 지표", "모델 카드", "위해 통제"])

with tab_log:
    if not can("view_audit"):
        st.info("전체 감사 로그는 감독자만 볼 수 있습니다. 위 지표는 모든 역할에 표시됩니다.")
    elif not ss.audit.events:
        st.info("아직 기록이 없습니다. 전원 오케스트레이터에서 케이스를 처리하면 추천·결정·오버라이드·연락 결과가 "
                "시간순으로 남습니다.")
    else:
        def detail(e):
            if e["event"] == "recommendation":
                return ", ".join(f'#{o["rank"]} {o["hospital"]} (점수 {o["accept_score"]:.0%}, {o["confidence"]})'
                                 for o in e["options"]) + (f' · 안전 플래그: {", ".join(e["safety_flags"])}'
                                                          if e.get("safety_flags") else "")
            if e["event"] in ("select", "override", "escalation"):
                return f'{e.get("hospital") or "의료지도"} · 추천순위 {e.get("recommended_rank")}'
            if e["event"] == "contact_outcome":
                return (f'{e["hospital"]} (추천 {e.get("recommended_rank")}순위) → '
                        f'{"수용" if e["accepted"] else "거절"}')
            if e["event"] in ("login", "logout"):
                return f'{e.get("user", "")} {e.get("role", "")}'.strip()
            return "의료진이 필드 확인 · 요청 시각 기록"

        df = pd.DataFrame([{
            "#": e["seq"], "시각(UTC)": e["timestamp"], "환경": e.get("environment", ""),
            "케이스": e["case_id"], "이벤트": e["event"], "모드": e.get("mode", ""), "상세": detail(e),
            "사유": e.get("override_reason") or e.get("reason") or "",
            "사용자": e.get("user", ""), "지연(ms)": e.get("latency_ms"),
        } for e in ss.audit.events])
        st.dataframe(df, hide_index=True, width="stretch")
        if can("export_audit"):
            st.download_button("감사 로그 다운로드 (.jsonl)",
                               "\n".join(json.dumps(e, ensure_ascii=False) for e in ss.audit.events),
                               file_name="synapse_h_audit.jsonl", mime="application/x-ndjson")

with tab_pilot:
    st.caption("제안서 Table 11 — 아래 임계값은 경영진 제안이며 달성 결과가 아닙니다. 데이터 분석 전 임상·통계 "
               "파트너와 확정합니다. ‘현재 세션’ 값은 이 데모 세션의 기록에서 계산됩니다.")
    st.dataframe(pd.DataFrame([
        ["주요 운영", "전원 요청→목적지 확정 시간 중앙값", "사전 정의 기준 대비 ≥15% 단축",
         num(m["median_measured_min"], "{:.1f}", "분 (실측)")],
        ["매칭", "모델 1순위 수용률", "≥8%p 개선", pct(m["model_top1_accept"])],
        ["매칭", "첫 통화 수용률 (선택 순위 무관)", "참고 지표", pct(m["first_contact_accept"])],
        ["부담", "케이스당 평균 연락 수 (미해결 포함)", "≥10% 감소", num(m["mean_contacts"])],
        ["완결", "연락한 케이스 중 수용 확정 비율", "추적 지표", pct(m["resolved_rate"])],
        ["이송 가드레일", "이송 시간 중앙값 변화", "+2분 이하 (역량 이점 문서화 시 예외)", "고위험 환자는 의료지도 확인으로 에스컬레이션"],
        ["추출", "의료진 검토 후 필수 필드 정확도", "≥95%; 근거 없는 핵심 필드 삽입 0", "확인 양식 강제"],
        ["안전", "치명적 위험 추천률", "판정 세트 0건; 센티넬 이벤트 시 중지", "독립 검토 필요"],
        ["보정", "수용 예측 보정", "기울기/절편 사전 한계 내", "파트너 데이터 필요"],
        ["형평성", "연령·성별·지역·언어·질환별 성능", "설명되지 않는 격차 없음", "파트너 데이터 필요"],
        ["신뢰성", "가용성·피드 신선도", "≥99.5% 가동; 피드 신선도 100% 표시", "100% 표시"],
        ["사람의 통제", "최종 결정 확인", "100% 사람 확인; 오버라이드 사유 기록", "강제 (UI)"],
    ], columns=["영역", "지표", "Go/no-go 임계값 (제안)", "현재 세션"]), hide_index=True, width="stretch")

with tab_card:
    st.markdown(f"""
**모델 버전** `{MODEL_VERSION}`

| 항목 | 내용 |
|---|---|
| 의도된 용도 | 병원 간 응급 전원 시 *운영* 준비도 점수 산출과 목적지 순위 제안. 권한 있는 의료진이 최종 선택 |
| 출력의 의미 | **수용 점수**는 합성 계수로 계산한 0–1 사이 값이며 실제 수용 확률로 보정·검증되지 않았습니다. 구간과 신뢰도 라벨도 실측 불확실성이 아닌 규칙 기반 표시입니다 |
| 검증 계획 | 파트너 데이터 확보 후 Brier score, log loss, 보정 곡선, 예측 구간 포함률, 병원·질환별 성능을 보고 (TRIPOD+AI) |
| 사용 금지 | 자율 이송 지시, 진단, 생존 확률 제시, 공개 병원 평판 순위 |
| 학습 데이터 | 없음 — 합성 계수 (logistic baseline). 파트너 데이터로 재적합 필요 |
| 입력 | 과거 수용률, 현재 부하, 야간 여부, 마지막 병상 여부, 피드 신선도 |
| 계수 | {", ".join(f"{k}={v:+.2f}" for k, v in COEF.items())} |
| 결측/지연 처리 | 피드 {STALE_THRESHOLD_MIN:.0f}분 초과 → 사전확률(0.5)로 수축·불확실성 확대·경고; {UNVERIFIABLE_MIN:.0f}분 초과 → 전화 확인 전 제외 |
| Abstention | 필수 필드 누락/범위 밖 → 랭킹 차단; 적격 병원 없음 → 의료지도; 1순위 신뢰도 낮음 → 의료지도 권고 |
| 알려진 한계 | 보정·하위집단 성능 미검증; 소규모 합성 네트워크; 규칙 기반 추출은 표현 다양성에 취약 (합성 메모 40건 중 표현을 바꾼 10건에서 필드 71% 정답, 잘못된 값 제안 0건). LLM 추출기는 선택 사항이며 근거 원문 검증과 규칙 교차 확인을 거침 |
| 보고 기준 | 예측 모델 TRIPOD+AI, 초기 임상 평가 DECIDE-AI, GMLP 원칙 |
""")

with tab_hazard:
    st.caption("제안서 Table 27 — 위해와 안전한 실패 방식, 그리고 이 데모에서 구현된 통제")
    st.dataframe(pd.DataFrame([
        ["잘못된 역량 매칭", "하드코딩된 경로 요건; 의료진 확인", "추천 차단; 에스컬레이션",
         "✅ Capability Registry 하드 제약"],
        ["오래되거나 잘못된 병상 정보", "타임스탬프·출처 표시; 신선도 임계값", "하향 가중 또는 제외; 경고",
         "✅ 15분 하향가중 / 60분 제외"],
        ["NLP 환각·누락", "근거 원문, 스키마·범위 검사, 필드 신뢰도, 사람 확인", "Abstain; 수동 입력 요구",
         "✅ 근거 하이라이트 + 확인 양식"],
        ["과신한 예측", "보정 모니터링, 구간, OOD 감지", "낮은 신뢰도 라벨 또는 순위 없음",
         "✅ 신뢰도 라벨 + 구간"],
        ["자동화 편향", "대안·근거 표시; 오버라이드·일치율 측정", "UX 재설계 / 범위 제한",
         "✅ Shadow mode + 오버라이드 사유"],
        ["불균등한 성능", "하위집단 평가, 공정성 제약", "재보정·제한·중단", "◻ 파트너 데이터 필요"],
        ["사이버 사고", "분리, 로깅, 백업, 대응 플레이북", "격리; 수동 워크플로로 안전 실패",
         "◐ 계정·역할, 추가 전용 감사 로그(해시 체인) 구현 · 분리·백업·대응 절차는 운영 단계"],
        ["시스템 불가용", "수동 대체 절차 문서화; 가동 모니터링", "기존 전화/공공 워크플로로 복귀", "◻ 운영 단계"],
    ], columns=["위해", "예방/감지", "안전한 대응", "데모 구현"]), hide_index=True, width="stretch")
    st.markdown('<div class="sh-boundary"><span class="sh-eyebrow">Governance promise</span>시스템은 불확실해도 됩니다. 불완전하거나 '
                "오래된 데이터로 만든 정밀해 보이는 점수보다, 눈에 보이는 abstention과 에스컬레이션이 더 안전하고 "
                "신뢰할 수 있습니다.</div>", unsafe_allow_html=True)
