"""Case ranking workspace: capture → confirm → match → decide → learn."""

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import (STATUS, TERM_COLORS, esc, hour, next_case_id, plotly_layout)
from synapse_h.capabilities import PATHWAYS, required_capabilities
from synapse_h.data import SCENARIOS, travel_minutes
from synapse_h.fhir import case_bundle
from synapse_h.intake import (FIELD_LABELS, OPTIONAL_FIELDS, REQUIRED_FIELDS,
                              RuleBasedExtractor, build_case)
from synapse_h.models import CAPABILITY_LABELS
from synapse_h.optimizer import TERM_LABELS, eligibility, rank_destinations
from synapse_h.readiness import CONFIDENCE_KO, predict_readiness

ss = st.session_state
ss.setdefault("orch", {"stage": "capture"})
ss.setdefault("transfers", [])
O = ss.orch
SCEN = {s["id"]: s for s in SCENARIOS}
REFUSAL_REASONS = ["가용 병상 없음", "담당 전문의 부재", "장비 사용 중", "중환자실 포화", "기타"]


def reset_case():
    ss.orch = {"stage": "capture"}


def mode_label():
    return "SHADOW MODE" if ss.mode == "shadow" else "CONTROLLED PILOT"


st.markdown(f'<div class="sh-bar"><b>SYNAPSE-H &nbsp;|&nbsp; TRANSFER ORCHESTRATOR</b>'
            f'<span>{mode_label()}</span></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 1. Capture
# ---------------------------------------------------------------------------
def capture():
    st.subheader("① Capture — 의뢰 정보 입력")
    st.caption("의뢰서, 활력징후, Pre-KTAS를 자유 텍스트로 입력하세요. 언어 모델은 필드를 *제안*할 뿐이며, "
               "결정적 검증기와 의료진이 확인합니다.")
    c1, c2 = st.columns([2, 1])
    sid = c1.selectbox("데모 시나리오 (합성 예시)", list(SCEN), format_func=lambda k: SCEN[k]["title"])
    origin_ids = list(ss.origins)
    oid = c2.selectbox("의뢰 기관", origin_ids, index=origin_ids.index(SCEN[sid]["origin"]),
                       format_func=lambda k: ss.origins[k].name, key=f"origin_{sid}")
    note = st.text_area("의뢰서 (Referral note)", SCEN[sid]["note"], height=130, key=f"note_{sid}")
    if st.button("🔎 구조화 추출 실행", type="primary"):
        O.update(stage="confirm", note=note, origin_id=oid, intake=RuleBasedExtractor().extract(note))
        st.rerun()


# ---------------------------------------------------------------------------
# 2. Confirm
# ---------------------------------------------------------------------------
def highlight(note: str, fields) -> str:
    spans = sorted({f.span for f in fields.values() if f.span and f.span[1] > f.span[0]})
    out, pos = [], 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(esc(note[pos:s]))
        out.append(f'<mark class="ev">{esc(note[s:e])}</mark>')
        pos = e
    out.append(esc(note[pos:]))
    return "".join(out)


def confirm():
    res = O["intake"]
    st.subheader("② Confirm — 추출 필드 확인 (Human confirmation)")
    st.markdown(f'<div class="sh-case">{highlight(res.note, res.fields)}</div>', unsafe_allow_html=True)
    st.caption("노란 표시는 각 필드의 근거 원문(evidence span)입니다.")

    rows = []
    for name in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        f = res.fields[name]
        value = PATHWAYS[f.value].label if name == "pathway" and f.value else f.value
        rows.append({
            "필드": FIELD_LABELS[name] + (" *" if name in REQUIRED_FIELDS else ""),
            "제안 값": "—" if value is None else str(value),
            "상태": {"extracted": "✅ 추출", "missing": "⬜ 누락", "invalid": "⛔ 범위 밖"}[f.status],
            "신뢰도": f"{f.confidence:.0%}" if f.confidence else "—",
            "근거": f.evidence,
            "메모": f.message,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if res.red_flags:
        st.warning("🚩 Red flags: " + ", ".join(res.red_flags))
    if not res.can_proceed:
        st.error(f"**자동 추출만으로는 진행할 수 없습니다 (Abstain).** {res.abstain_message}. "
                 "아래 양식에서 원문 또는 의뢰 기관 확인 후 직접 입력하세요.")

    f = res.fields
    with st.form("confirm_form"):
        st.markdown("**의료진 확인 양식** — 모든 값은 저장 전에 다시 검증됩니다.")
        c1, c2, c3, c4 = st.columns(4)
        age = c1.number_input("나이 *", value=f["age"].value, step=1)
        sex_opts = ["male", "female"]
        sex = c2.selectbox("성별 *", sex_opts, index=sex_opts.index(f["sex"].value) if f["sex"].value else None,
                           format_func=lambda s: {"male": "남", "female": "여"}[s], placeholder="선택")
        pw_keys = list(PATHWAYS)
        pathway = c3.selectbox("임상 경로 *", pw_keys,
                               index=pw_keys.index(f["pathway"].value) if f["pathway"].value else None,
                               format_func=lambda k: PATHWAYS[k].label, placeholder="임상의 선택")
        ktas = c4.selectbox("Pre-KTAS *", [1, 2, 3, 4, 5],
                            index=f["ktas"].value - 1 if f["ktas"].status == "extracted" else None,
                            placeholder="입력/규칙 기반만")
        c1, c2, c3, c4 = st.columns(4)
        sbp = c1.number_input("수축기 혈압 *", value=f["sbp"].value, step=1)
        dbp = c2.number_input("이완기 혈압", value=f["dbp"].value, step=1)
        hr = c3.number_input("맥박 *", value=f["hr"].value, step=1)
        spo2 = c4.number_input("SpO₂ % *", value=f["spo2"].value, step=1)
        c1, c2, c3 = st.columns(3)
        rr = c1.number_input("호흡수", value=f["rr"].value, step=1)
        gcs = c2.number_input("GCS", value=f["gcs"].value, step=1)
        onset = c3.number_input("발병/LKW 후 경과(분) *", value=f["onset_min"].value, step=1)
        if onset is not None:
            now = datetime.combine(datetime.today(), ss.clock)
            st.caption(f"⏱️ 절대 시각 확인: 발병/최종정상 시각 ≈ **{(now - timedelta(minutes=onset)):%H:%M}** "
                       f"(현재 {now:%H:%M} 기준)")
        if pathway:
            caps = required_capabilities(pathway, age)
            st.caption("필수 역량 (Hard constraints): " + ", ".join(CAPABILITY_LABELS[c] for c in sorted(caps)))
        ok = st.checkbox(f"위 필드를 원문과 대조해 확인했습니다 — {ss.user}")
        submitted = st.form_submit_button("✅ 확인 및 매칭 실행", type="primary")

    if submitted:
        if not ok:
            st.error("의료진 확인 체크가 필요합니다. 확인되지 않은 필드는 랭킹에 사용되지 않습니다.")
            return
        values = dict(age=age, sex=sex, pathway=pathway, ktas=ktas, sbp=sbp, dbp=dbp, hr=hr,
                      spo2=spo2, rr=rr, gcs=gcs, onset_min=onset)
        try:
            case = build_case("pending", O["origin_id"], values, res.note, res.red_flags, ss.user)
        except ValueError as e:
            st.error(f"검증 실패: {e}")
            return
        case.case_id = next_case_id()
        n_conf = sum(values[k] is not None for k in REQUIRED_FIELDS + OPTIONAL_FIELDS)
        O.update(stage="decide", case=case, refused=set(), contacts=[], revealed=False,
                 fields_confirmed=f"{n_conf}/{len(REQUIRED_FIELDS + OPTIONAL_FIELDS)}")
        st.rerun()
    if st.button("← 다시 입력"):
        reset_case()
        st.rerun()


# ---------------------------------------------------------------------------
# 3-4. Match & decide
# ---------------------------------------------------------------------------
def case_header(case, rec):
    fresh = min((o.hospital.feed_age_min for o in rec.options), default=None)
    caps = ", ".join(CAPABILITY_LABELS[c] for c in sorted(required_capabilities(case.pathway, case.age)))
    if fresh is None:
        pill = ""
    elif max(o.hospital.feed_age_min for o in rec.options) > 15:
        pill = f'<span class="sh-pill" style="color:#a4510f;border-color:{STATUS["serious"]}">⚠ STALE FEED</span>'
    else:
        pill = f'<span class="sh-pill" style="color:#0f7f6e;border-color:#1baf7a">DATA FRESH {fresh:.0f}m</span>'
    sex = {"male": "남", "female": "여"}[case.sex]
    st.markdown(
        f'<div class="sh-case"><div class="cid">CASE {esc(case.case_id)} · {esc(ss.origins[case.origin_id].name)}</div>'
        f'<div class="title">{esc(PATHWAYS[case.pathway].label)} • Pre-KTAS {case.ktas} • onset {case.onset_min:.0f} min ago {pill}</div>'
        f'<div class="sub">{case.age}세 {sex} · BP {case.sbp}/{case.dbp or "–"} · HR {case.hr} · SpO₂ {case.spo2}%'
        f'{" · GCS " + str(case.gcs) if case.gcs else ""} &nbsp;|&nbsp; 필요 역량: {esc(caps)} &nbsp;|&nbsp; '
        f'추출 필드 {O.get("fields_confirmed", "")} 의료진 확인</div></div>', unsafe_allow_html=True)


def option_card(o, top: bool):
    r = o.readiness
    warn = "".join(f'<div class="sh-warn">⚠ {esc(w)}</div>' for w in o.warnings)
    return (
        f'<div class="sh-card{" top" if top else ""}"><div class="row">'
        f'<div style="display:flex"><span class="sh-rank">{o.rank}</span><div>'
        f'<div class="sh-name">{esc(o.hospital.name)} <span style="color:#898781;font-weight:400;font-size:.8rem">'
        f'{esc(o.hospital.tier)}</span></div><div class="sh-reason">{esc(o.reason)}</div>{warn}</div></div>'
        f'<div class="sh-eta">ETA <b>{o.travel_min:.0f} min</b><br>'
        f'예측 수용 <b>{r.accept_prob:.0%}</b> <span style="color:#898781">({r.low:.0%}–{r.high:.0%})</span><br>'
        f'신뢰도 {CONFIDENCE_KO[r.confidence]} · 피드 {o.hospital.feed_age_min:.0f}분 전</div>'
        f'</div></div>')


def cost_chart(rec):
    fig = go.Figure()
    names = [f"#{o.rank} {o.hospital.name}" for o in rec.options][::-1]
    for term, label in TERM_LABELS.items():
        vals = [o.terms[term] for o in rec.options][::-1]
        fig.add_bar(y=names, x=vals, name=label, orientation="h", marker_color=TERM_COLORS[term],
                    marker_line=dict(color="#fcfcfb", width=2),
                    hovertemplate=f"{label}: %{{x:.1f}}<extra>%{{y}}</extra>")
    fig.update_layout(barmode="stack", xaxis_title="가중 비용 (분 환산, 낮을수록 좋음)")
    st.plotly_chart(plotly_layout(fig, height=110 + 50 * len(rec.options)), use_container_width=True)


def log_recommendation(rec):
    key = (rec.case.case_id, tuple(sorted(O["refused"])), ss.weights.as_tuple(), ss.mode, hour())
    if O.get("logged_key") != key:
        ss.audit.recommendation(rec, ss.mode)
        O["logged_key"] = key


def start_contact(hid, rank, reason=""):
    ss.audit.decision(O["case"].case_id, hid, rank, reason, ss.mode, ss.user)
    O.update(stage="contact", contact=hid, contact_rank=rank)
    st.rerun()


def escalate(rec, reason):
    ss.audit.decision(O["case"].case_id, None, None, reason, ss.mode, ss.user)
    ss.transfers.append({"case_id": O["case"].case_id, "origin": O["case"].origin_id,
                         "hospital": None, "status": "에스컬레이션"})
    O.update(stage="done", outcome="escalated", esc_reason=reason)
    st.rerun()


def decide():
    case = O["case"]
    origin = ss.origins[case.origin_id]
    rec = rank_destinations(case, ss.network, origin, ss.weights, hour(), O["refused"])
    log_recommendation(rec)
    case_header(case, rec)
    if O["refused"]:
        st.info("거절된 병원: " + ", ".join(h.name for h in ss.network if h.id in O["refused"])
                + " → 제외 후 재순위화했습니다.")

    if rec.escalate:
        st.markdown(f'<div class="sh-esc"><b>🚨 ESCALATE TO MEDICAL CONTROL</b><br>{esc(rec.escalation_reason)}</div>',
                    unsafe_allow_html=True)
        st.write("")

    eligible = [h for h in ss.network if eligibility(case, h, O["refused"]) is None]
    full = rank_destinations(case, ss.network, origin, ss.weights, hour(), O["refused"], top_k=99)
    rank_of = {o.hospital.id: o.rank for o in full.options}

    hide = ss.mode == "shadow" and not O.get("revealed")
    if hide and eligible:
        st.subheader("Shadow mode — 추천을 보기 전에 결정을 기록하세요")
        st.caption("추천은 진료팀에 숨겨지고 결정 후에 공개됩니다. 진료에 영향을 주지 않고 실제 선택과 비교합니다.")
        options = sorted(eligible, key=lambda h: h.name)
        choice = st.radio("이송할 병원 (필수 역량 충족 병원, 이름순)", [h.id for h in options],
                          format_func=lambda i: next(f"{h.name} · ETA {travel_minutes(origin, h):.0f}분"
                                                     for h in options if h.id == i))
        c1, c2 = st.columns(2)
        if c1.button("내 결정 기록 후 추천 공개", type="primary"):
            O.update(revealed=True, shadow_choice=choice)
            st.rerun()
        if c2.button("📞 의료지도 호출"):
            escalate(rec, "Shadow mode 사용자 판단")
        return

    if O.get("shadow_choice"):
        sc = O["shadow_choice"]
        r = rank_of.get(sc)
        agree = "✅ 추천 1순위와 일치" if r == 1 else f"↔ 추천 {r}순위 (불일치는 학습 신호로 기록)"
        st.success(f"당신의 결정: **{next(h.name for h in ss.network if h.id == sc)}** — {agree}")

    if rec.options:
        st.subheader("③ Match · ④ Decide — 추천 목적지 Top 3")
        for o in rec.options:
            c1, c2 = st.columns([6, 1])
            c1.markdown(option_card(o, o.rank == 1), unsafe_allow_html=True)
            if not O.get("shadow_choice"):
                if o.rank == 1:
                    if c2.button("SELECT", key=f"sel_{o.hospital.id}", type="primary", use_container_width=True):
                        start_contact(o.hospital.id, 1)
                else:
                    if c2.button("SELECT", key=f"sel_{o.hospital.id}", use_container_width=True,
                                 help="1순위가 아닌 선택은 오버라이드이며 사유가 필요합니다"):
                        O["pending_override"] = o.hospital.id
                        st.rerun()
        st.markdown(f'<div class="sh-why"><b>WHY #1</b> &nbsp;{esc(rec.why_top)}</div>', unsafe_allow_html=True)
        st.write("")

    if O.get("shadow_choice"):
        sc = O["shadow_choice"]
        if st.button("📞 내 결정 병원에 연락 시작", type="primary"):
            reason = "" if rank_of.get(sc) == 1 else "Shadow mode — 사용자 독립 결정"
            O["shadow_choice"] = None
            O["revealed"] = False
            start_contact(sc, rank_of.get(sc), reason)
    elif eligible:
        c1, c2 = st.columns([3, 1])
        with c1.expander("✍️ OVERRIDE — 다른 병원 선택 (사유 필수)", expanded=bool(O.get("pending_override"))):
            ids = [h.id for h in sorted(eligible, key=lambda h: rank_of[h.id])]
            pre = O.get("pending_override")
            hid = st.selectbox("병원", ids, index=ids.index(pre) if pre in ids else 0,
                               format_func=lambda i: f"#{rank_of[i]} " + next(h.name for h in eligible if h.id == i))
            reason = st.text_input("오버라이드 사유 (예: 환자·보호자 선호, 최근 통화로 확인된 정보)")
            if st.button("오버라이드로 연락 시작"):
                if not reason.strip() and rank_of[hid] != 1:
                    st.error("오버라이드 사유를 입력해야 합니다 — 불일치는 중요한 학습 신호입니다.")
                else:
                    O["pending_override"] = None
                    start_contact(hid, rank_of[hid], reason.strip())
        if c2.button("📞 CALL MEDICAL CONTROL", use_container_width=True):
            escalate(rec, rec.escalation_reason or "사용자 판단으로 의료지도 호출")
    else:
        if st.button("📞 CALL MEDICAL CONTROL", type="primary"):
            escalate(rec, rec.escalation_reason)

    if rec.options:
        with st.expander("📊 순위 근거 — 목적 함수 항목별 비용 (No hidden optimization)", expanded=False):
            cost_chart(rec)
            st.dataframe(pd.DataFrame([{
                "순위": o.rank, "병원": o.hospital.name, "이동(분)": o.travel_min,
                "승인지연(분)": o.hospital.confirm_delay_min, "예측 수용": f"{o.readiness.accept_prob:.0%}",
                "부하": f"{o.hospital.load:.0%}", "불확실성": round(o.readiness.uncertainty, 2),
                "예상 승인+이송(분)": round(o.expected_time_min, 1), "총 비용": round(o.cost, 1),
            } for o in full.options]), hide_index=True, use_container_width=True)
    with st.expander(f"🚫 제외된 병원 {len(rec.excluded)}곳 — Hard constraints"):
        st.dataframe(pd.DataFrame([{"병원": e.hospital.name, "등급": e.hospital.tier, "제외 사유": e.reason}
                                   for e in rec.excluded]), hide_index=True, use_container_width=True)
    st.caption(f"모델: {rec.model_version} · 계산 {rec.latency_ms:.1f} ms")


# ---------------------------------------------------------------------------
# Coordination channel
# ---------------------------------------------------------------------------
def contact():
    h = next(x for x in ss.network if x.id == O["contact"])
    st.subheader(f"📞 연락 중 — {h.name}")
    st.caption("케이스 패킷(FHIR 번들)이 전원 데스크로 전송되었다고 가정합니다. 응답 결과를 기록하세요.")
    n_prev = len(O["contacts"])
    st.markdown(f"연락 시도 **{n_prev + 1}회차** · 추천 순위 **{O['contact_rank']}** · "
                f"전원 데스크 평균 응답 {h.confirm_delay_min:.0f}분")
    c1, c2, c3 = st.columns(3)
    if c1.button("✅ 수용 (Accepted)", type="primary", use_container_width=True):
        record_outcome(h, True)
    reason = c2.selectbox("거절 사유", REFUSAL_REASONS, label_visibility="collapsed")
    if c2.button("❌ 거절 (Refused)", use_container_width=True):
        record_outcome(h, False, reason)
    if c3.button("🎲 응답 시뮬레이션", use_container_width=True,
                 help="예측 수용 확률로 응답을 무작위 생성합니다 (데모용)"):
        p = predict_readiness(h, hour()).accept_prob
        accepted = bool(np.random.default_rng().random() < p)
        record_outcome(h, accepted, "" if accepted else str(np.random.default_rng().choice(REFUSAL_REASONS[:4])))


def record_outcome(h, accepted, reason=""):
    case = O["case"]
    ss.audit.contact_outcome(case.case_id, h.id, accepted, reason)
    O["contacts"].append({"hospital": h.name, "accepted": accepted, "reason": reason})
    if accepted:
        h.beds_available = max(0, h.beds_available - 1)
        ss.transfers.append({"case_id": case.case_id, "origin": case.origin_id, "hospital": h.id, "status": "수용"})
        O.update(stage="done", outcome="accepted", destination=h.id)
    else:
        O["refused"].add(h.id)
        O.update(stage="decide", revealed=False, shadow_choice=None)
    st.rerun()


# ---------------------------------------------------------------------------
# 5. Learn
# ---------------------------------------------------------------------------
def done():
    case = O["case"]
    if O["outcome"] == "accepted":
        h = next(x for x in ss.network if x.id == O["destination"])
        fails = len(O["contacts"]) - 1
        st.success(f"### ✅ 전원 확정: {h.name}\n연락 {len(O['contacts'])}회 · 모의 승인 시간 "
                   f"{3 + 6 * fails:.0f}분 (첫 연락 3분 + 실패당 6분) · ETA "
                   f"{travel_minutes(ss.origins[case.origin_id], h):.0f}분")
    else:
        h = None
        st.markdown(f'<div class="sh-esc"><b>🚨 의료지도(Medical Control)로 에스컬레이션됨</b><br>'
                    f'{esc(O.get("esc_reason", ""))}</div>', unsafe_allow_html=True)
        st.write("")

    st.subheader("⑤ Learn — 이 케이스의 감사 추적")
    events = [e for e in ss.audit.events if e["case_id"] == case.case_id]
    st.dataframe(pd.DataFrame([{
        "#": e["seq"], "시각(UTC)": e["timestamp"][11:19], "이벤트": e["event"],
        "병원": e.get("hospital") or ", ".join(o["hospital"] for o in e.get("options", [])),
        "추천순위": e.get("recommended_rank"), "수용": e.get("accepted"),
        "사유": e.get("override_reason") or e.get("reason") or "", "모드": e.get("mode", ""),
    } for e in events]), hide_index=True, use_container_width=True)

    bundle = case_bundle(case, h)
    with st.expander("🧾 FHIR R5 케이스 번들 (Patient · Observation · Condition · ServiceRequest · Task)"):
        st.json(bundle, expanded=False)
    c1, c2 = st.columns(2)
    c1.download_button("FHIR 번들 다운로드 (.json)", json.dumps(bundle, ensure_ascii=False, indent=2),
                       file_name=f"{case.case_id}_bundle.json", mime="application/fhir+json",
                       use_container_width=True)
    if c2.button("➕ 새 케이스", type="primary", use_container_width=True):
        reset_case()
        st.rerun()


{"capture": capture, "confirm": confirm, "decide": decide, "contact": contact, "done": done}[O["stage"]]()
