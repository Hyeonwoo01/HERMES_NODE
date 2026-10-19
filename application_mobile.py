"""SYNAPSE-H mobile — one screen for phones and tablets.

Enter the referral data, confirm what was extracted, get ranked destinations.
No settings: default weights, controlled-pilot mode and the current Korean
time are used. Extracted fields are never ranked until a clinician confirms
them, and the clinician still picks the hospital and records the response.

Run from the repository root:  streamlit run application_mobile.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import streamlit as st  # noqa: E402

from common import CSS, INK, esc, header  # noqa: E402
from synapse_h.audit import AuditLog  # noqa: E402
from synapse_h.capabilities import PATHWAYS, required_capabilities  # noqa: E402
from synapse_h.data import SCENARIOS, default_network, origins, travel_minutes  # noqa: E402
from synapse_h.intake import (FIELD_LABELS, REQUIRED_FIELDS, RuleBasedExtractor,  # noqa: E402
                              build_case)
from synapse_h.models import CAPABILITY_LABELS  # noqa: E402
from synapse_h.optimizer import Weights, rank_destinations  # noqa: E402
from synapse_h.readiness import CONFIDENCE_KO  # noqa: E402

st.set_page_config(page_title="SYNAPSE-H", page_icon="🚑", layout="centered",
                   initial_sidebar_state="collapsed")

MOBILE_CSS = f"""
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"],
header[data-testid="stHeader"] {{display:none!important}}
[data-testid="stAppViewContainer"] .block-container {{max-width:760px;padding:1.25rem 1rem 4rem}}
[data-testid^="stBaseButton"] {{min-height:52px}}
[data-testid^="stBaseButton"] p {{font-size:1.05rem}}
textarea {{font-size:1rem!important}}
.m-summary {{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
.m-chip {{background:#FFFFFF;border:1px solid rgba(20,20,19,0.12);border-radius:999px;padding:4px 12px;
  font-size:.85rem;color:{INK}}}
.m-done {{background:#FFFFFF;border-radius:32px;padding:24px 26px;border:1.5px solid {INK}}}
.m-done h3 {{margin:6px 0 8px;padding:0}}
@media (max-width: 767px) {{ .sh-name small {{display:block;margin-left:0;margin-top:2px}} }}
</style>
"""
st.markdown(CSS + MOBILE_CSS, unsafe_allow_html=True)

ss = st.session_state
if "m" not in ss:
    ss.m = {"stage": "input", "values": {}}
    ss.m_network = default_network()
    ss.m_origins = origins()
    ss.m_audit = AuditLog()
    ss.m_seq = 2000
M = ss.m
SCEN = {s["id"]: s for s in SCENARIOS}
OVERRIDE_REASONS = ["보호자·환자 요청", "최근 통화로 확인된 정보", "임상적 판단", "기타"]
REFUSAL_REASONS = ["가용 병상 없음", "담당 전문의 부재", "장비 사용 중", "중환자실 포화", "기타"]


def now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def reset():
    ss.m = {"stage": "input", "values": {}}
    ss.pop("sample", None)


def go(stage, **kw):
    M.update(stage=stage, **kw)
    st.rerun()


header("응급 전원 추천", "Mobile")


# ---------------------------------------------------------------------------
# Input: paste the referral, or type the fields directly
# ---------------------------------------------------------------------------
def make_case(values: dict, note: str, red_flags: list[str]):
    try:
        case = build_case("pending", M["origin_id"], values, note, red_flags, "mobile clinician (confirmed)")
    except ValueError as e:
        return None, str(e)
    ss.m_seq += 1
    case.case_id = f"M-{ss.m_seq}"
    return case, ""


STATUS_TAG = {"extracted": "✓ 원문에서 추출", "missing": "⚠ 입력 필요", "invalid": "⛔ 범위 밖 · 수정 필요"}


def highlight(note: str, fields) -> str:
    spans = sorted({f.span for f in fields.values() if f.span and f.span[1] > f.span[0]})
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue
        out += [esc(note[pos:a]), f'<mark class="ev">{esc(note[a:b])}</mark>']
        pos = b
    return "".join(out) + esc(note[pos:])


def input_view():
    st.markdown("**환자 정보를 넣고, 추출된 내용을 확인하면 받을 수 있는 병원을 추천합니다.**")
    origin_ids = list(ss.m_origins)
    M["origin_id"] = st.selectbox("의뢰 기관", origin_ids,
                                  index=origin_ids.index(M.get("origin_id", "O1")),
                                  format_func=lambda k: ss.m_origins[k].name)
    tab_note, tab_form = st.tabs(["의뢰 메모로 입력", "항목별 직접 입력"])

    with tab_note:
        sample = st.pills("예시 불러오기", ["stroke", "trauma", "pediatric", "stemi"],
                          format_func=lambda k: SCEN[k]["title"].split(" (")[0], key="sample")
        if sample and M.get("sample") != sample:
            M.update(sample=sample, note=SCEN[sample]["note"], origin_id=SCEN[sample]["origin"])
            st.rerun()
        note = st.text_area("의뢰 메모", M.get("note", ""), height=150,
                            placeholder="예) 72세 남성, 안면마비, 편마비. 발생 40분 전. BP 160/90, HR 92, "
                                        "SpO2 96%. Pre-KTAS 2.")
        if st.button("🔎 정보 추출", type="primary", width="stretch"):
            if not note.strip():
                st.error("의뢰 메모를 입력하세요.")
            else:
                ss.m_seq += 1
                go("confirm", note=note, extraction=RuleBasedExtractor().extract(note), draft_id=ss.m_seq)

    with tab_form:
        with st.form("direct"):
            c1, c2 = st.columns(2)
            age = c1.number_input("나이", value=None, step=1)
            sex = c2.selectbox("성별", ["male", "female"], index=None,
                               format_func=lambda s: {"male": "남", "female": "여"}[s], placeholder="선택")
            pathway = st.selectbox("임상 경로", list(PATHWAYS), index=None,
                                   format_func=lambda k: PATHWAYS[k].label, placeholder="선택")
            c1, c2 = st.columns(2)
            ktas = c1.selectbox("Pre-KTAS", [1, 2, 3, 4, 5], index=None, placeholder="선택")
            onset = c2.number_input("발병 후 경과(분)", value=None, step=1)
            c1, c2, c3 = st.columns(3)
            sbp = c1.number_input("수축기 혈압", value=None, step=1)
            hr = c2.number_input("맥박", value=None, step=1)
            spo2 = c3.number_input("SpO₂ %", value=None, step=1)
            if st.form_submit_button("✅ 입력 확인 · 추천 보기", type="primary", width="stretch"):
                values = dict(age=age, sex=sex, pathway=pathway, ktas=ktas, onset_min=onset,
                              sbp=sbp, hr=hr, spo2=spo2)
                case, err = make_case(values, "", [])
                if case:
                    go("result", case=case, refused=set(), contacts=[])
                st.error(err)


# ---------------------------------------------------------------------------
# Confirm: the clinician checks every extracted field before ranking runs
# ---------------------------------------------------------------------------
def confirm_view():
    res = M["extraction"]
    f = res.fields
    st.markdown('<span class="sh-eyebrow">의료진 확인</span>', unsafe_allow_html=True)
    st.markdown("**메모에서 읽은 값을 원문과 대조해 확인하세요.** 확인한 값만 추천에 사용합니다.")
    st.markdown(f'<div class="sh-case">{highlight(res.note, f)}</div>', unsafe_allow_html=True)
    if res.red_flags:
        st.warning("🚩 " + ", ".join(res.red_flags))
    need = res.missing + [k for k in res.invalid if k in REQUIRED_FIELDS]
    if need:
        st.warning("⚠ 표시된 항목을 채우거나 고쳐 주세요: " + ", ".join(FIELD_LABELS[k] for k in need))

    def lab(name):
        return f"{FIELD_LABELS[name]} · {STATUS_TAG[f[name].status]}"

    d = M["draft_id"]
    with st.form(f"confirm_{d}"):
        c1, c2 = st.columns(2)
        age = c1.number_input(lab("age"), value=f["age"].value, step=1, key=f"age_{d}")
        sex = c2.selectbox(lab("sex"), ["male", "female"],
                           index=["male", "female"].index(f["sex"].value) if f["sex"].value else None,
                           format_func=lambda x: {"male": "남", "female": "여"}[x], placeholder="선택", key=f"sex_{d}")
        keys = list(PATHWAYS)
        pathway = st.selectbox(lab("pathway"), keys, index=keys.index(f["pathway"].value) if f["pathway"].value else None,
                               format_func=lambda k: PATHWAYS[k].label, placeholder="선택", key=f"pw_{d}")
        c1, c2 = st.columns(2)
        ktas = c1.selectbox(lab("ktas"), [1, 2, 3, 4, 5],
                            index=f["ktas"].value - 1 if f["ktas"].status == "extracted" else None,
                            placeholder="선택", key=f"ktas_{d}")
        onset = c2.number_input(lab("onset_min"), value=f["onset_min"].value, step=1, key=f"onset_{d}")
        c1, c2, c3 = st.columns(3)
        sbp = c1.number_input(lab("sbp"), value=f["sbp"].value, step=1, key=f"sbp_{d}")
        hr = c2.number_input(lab("hr"), value=f["hr"].value, step=1, key=f"hr_{d}")
        spo2 = c3.number_input(lab("spo2"), value=f["spo2"].value, step=1, key=f"spo2_{d}")
        if onset is not None:
            st.caption(f"⏱️ 발병/최종정상 시각 ≈ {(now_kst() - timedelta(minutes=onset)):%H:%M} (지금 {now_kst():%H:%M})")
        ok = st.form_submit_button("✅ 원문과 맞습니다 · 추천 보기", type="primary", width="stretch")
    if ok:
        values = dict(age=age, sex=sex, pathway=pathway, ktas=ktas, onset_min=onset, sbp=sbp, hr=hr, spo2=spo2,
                      dbp=f["dbp"].value if f["dbp"].status == "extracted" else None,
                      rr=f["rr"].value if f["rr"].status == "extracted" else None,
                      gcs=f["gcs"].value if f["gcs"].status == "extracted" else None)
        case, err = make_case(values, res.note, res.red_flags)
        if case:
            go("result", case=case, refused=set(), contacts=[])
        st.error(err)
    if st.button("← 메모 다시 쓰기", width="stretch"):
        go("input")


# ---------------------------------------------------------------------------
# Result: ranked destinations, one tap to contact
# ---------------------------------------------------------------------------
def summary(case):
    sex = {"male": "남", "female": "여"}[case.sex]
    caps = ", ".join(CAPABILITY_LABELS[c] for c in sorted(required_capabilities(case.pathway, case.age)))
    chips = [f"{case.age}세 {sex}", f"Pre-KTAS {case.ktas}", f"발병 {case.onset_min:.0f}분",
             f"BP {case.sbp}", f"HR {case.hr}", f"SpO₂ {case.spo2}%"]
    st.markdown(
        f'<div class="sh-case"><span class="sh-eyebrow">{esc(ss.m_origins[case.origin_id].name)}</span>'
        f'<div class="title">{esc(PATHWAYS[case.pathway].label)}</div>'
        f'<div class="sub">필요 역량: {esc(caps)}</div>'
        f'<div class="m-summary">{"".join(f"<span class=m-chip>{esc(c)}</span>" for c in chips)}</div></div>',
        unsafe_allow_html=True)


def card(o):
    r = o.readiness
    warn = "".join(f'<div class="sh-warn">⚠ {esc(w)}</div>' for w in o.warnings)
    return (
        f'<div class="sh-card{" top" if o.rank == 1 else ""}"><div class="row">'
        f'<div style="display:flex"><span class="sh-rank">{o.rank}</span><div>'
        f'<div class="sh-name">{esc(o.hospital.name)}<small>{esc(o.hospital.tier)}</small></div>'
        f'<div class="sh-reason">{esc(o.reason)}</div>{warn}</div></div>'
        f'<div class="sh-eta">이동 <b>{o.travel_min:.0f}분</b><br>'
        f'수용 가능성 <b>{r.accept_prob:.0%}</b><br>'
        f'신뢰도 {CONFIDENCE_KO[r.confidence]}</div></div></div>')


def result_view():
    case = M["case"]
    rec = rank_destinations(case, ss.m_network, ss.m_origins[case.origin_id], Weights(),
                            now_kst().hour, M["refused"])
    if M.get("logged") != (case.case_id, len(M["refused"])):
        ss.m_audit.recommendation(rec, "pilot")
        M["logged"] = (case.case_id, len(M["refused"]))
    summary(case)
    if M["refused"]:
        st.info("거절한 병원을 빼고 다시 추천했습니다.")

    if rec.escalate:
        st.markdown(f'<div class="sh-esc"><span class="sh-eyebrow">의료지도 연락 필요</span>'
                    f'{esc(rec.escalation_reason)}</div>', unsafe_allow_html=True)
        st.write("")
        if not rec.options and st.button("📞 의료지도(Medical Control) 연락", type="primary", width="stretch"):
            ss.m_audit.decision(case.case_id, None, None, rec.escalation_reason)
            go("done", outcome="escalated")

    for o in rec.options:
        st.markdown(card(o), unsafe_allow_html=True)
        label = f"📞 {o.hospital.name}에 연락"
        if st.button(label, key=f"pick_{o.hospital.id}", type="primary" if o.rank == 1 else "secondary",
                     width="stretch"):
            if o.rank == 1:
                ss.m_audit.decision(case.case_id, o.hospital.id, 1)
                go("contact", contact=o.hospital.id)
            M["pending_override"] = o.hospital.id
            st.rerun()
        if M.get("pending_override") == o.hospital.id:
            reason = st.pills("1순위가 아닌 병원을 고른 이유", OVERRIDE_REASONS, key=f"why_{o.hospital.id}")
            if st.button("이 병원으로 연락", key=f"confirm_{o.hospital.id}", width="stretch", disabled=not reason):
                ss.m_audit.decision(case.case_id, o.hospital.id, o.rank, reason)
                go("contact", contact=o.hospital.id, pending_override=None)

    if rec.options:
        st.markdown(f'<div class="sh-why"><span class="sh-eyebrow">1순위인 이유</span>{esc(rec.why_top)}</div>',
                    unsafe_allow_html=True)
        st.write("")
        if st.button("📞 의료지도(Medical Control) 연락", width="stretch"):
            ss.m_audit.decision(case.case_id, None, None, "사용자 판단")
            go("done", outcome="escalated")
    if st.button("← 처음으로", width="stretch"):
        reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Contact outcome and confirmation
# ---------------------------------------------------------------------------
def contact_view():
    case = M["case"]
    h = next(x for x in ss.m_network if x.id == M["contact"])
    summary(case)
    st.markdown(f'<div class="sh-why"><span class="sh-eyebrow">연락 중</span>'
                f'<b>{esc(h.name)}</b> 전원 데스크에 연락하고 결과를 눌러 주세요.</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("✅ 수용했어요", type="primary", width="stretch"):
        ss.m_audit.contact_outcome(case.case_id, h.id, True)
        M["contacts"].append(h.name)
        h.beds_available = max(0, h.beds_available - 1)
        go("done", outcome="accepted", destination=h.id)
    reason = st.pills("거절 사유", REFUSAL_REASONS, key="refusal")
    if st.button("❌ 거절했어요 → 다음 병원 추천", width="stretch", disabled=not reason):
        ss.m_audit.contact_outcome(case.case_id, h.id, False, reason)
        M["contacts"].append(h.name)
        M["refused"].add(h.id)
        go("result")


def done_view():
    case = M["case"]
    if M["outcome"] == "accepted":
        h = next(x for x in ss.m_network if x.id == M["destination"])
        eta = travel_minutes(ss.m_origins[case.origin_id], h)
        st.markdown(
            f'<div class="m-done"><span class="sh-eyebrow">전원 확정</span><h3>{esc(h.name)}</h3>'
            f'예상 이동 {eta:.0f}분 · 연락 {len(M["contacts"])}회 · {now_kst():%H:%M} 확정</div>',
            unsafe_allow_html=True)
    else:
        st.markdown('<div class="sh-esc"><span class="sh-eyebrow">의료지도로 전달</span>'
                    "받을 수 있는 병원을 찾지 못해 의료지도(Medical Control)에 연락하도록 안내했습니다.</div>",
                    unsafe_allow_html=True)
    st.write("")
    if st.button("➕ 새 환자", type="primary", width="stretch"):
        reset()
        st.rerun()


{"input": input_view, "confirm": confirm_view, "result": result_view, "contact": contact_view, "done": done_view}[M["stage"]]()

st.caption("합성 데이터 데모입니다. 실제 환자·병원 정보가 아니며, 추천은 참고용이고 최종 결정은 의료진이 합니다.")
