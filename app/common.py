"""Shared session state, sidebar controls and styling for every page."""

from __future__ import annotations

import html
from datetime import time

import streamlit as st

from synapse_h.audit import AuditLog
from synapse_h.data import CONCURRENT_CASES, default_network, origins
from synapse_h.intake import build_case
from synapse_h.optimizer import TERM_LABELS, Weights

# Reference palette (dataviz skill): categorical slots in fixed order + status colors.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
TERM_COLORS = dict(zip(TERM_LABELS, SERIES))
NAVY = "#0b2545"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"


def init_state() -> None:
    ss = st.session_state
    if "network" not in ss:
        ss.network = default_network()
    if "origins" not in ss:
        ss.origins = origins()
    if "audit" not in ss:
        ss.audit = AuditLog()
    if "concurrent" not in ss:
        ss.concurrent = [build_case(d["case_id"], d["origin_id"], d) for d in CONCURRENT_CASES]
    ss.setdefault("case_seq", 1060)
    ss.setdefault("mode", "pilot")
    ss.setdefault("clock", time(14, 32))
    ss.setdefault("user", "전원 간호사 김OO")
    ss.setdefault("weights", Weights())


def sidebar() -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown("### ⚙️ 운영 설정")
        mode = st.radio(
            "운영 모드",
            ["pilot", "shadow"],
            format_func=lambda m: {"pilot": "Controlled pilot · 추천 표시",
                                   "shadow": "Shadow mode · 결정 후 공개"}[m],
            index=0 if ss.mode == "pilot" else 1,
            help="Shadow mode에서는 사용자가 먼저 병원을 선택한 뒤 추천이 공개되어 "
                 "진료에 영향을 주지 않고 성능을 비교합니다 (제안서 §4.3 Stage 3).",
        )
        ss.mode = mode
        ss.user = st.text_input("사용자 (권한 있는 의료진)", ss.user)
        ss.clock = st.time_input("시뮬레이션 시각", ss.clock, step=60 * 30)

        with st.expander("⚖️ 목적 함수 가중치 (w₁–w₅)"):
            st.caption("min Σ w₁T + w₂C + w₃(1−A)R + w₄L + w₅U + λF(x)")
            w = ss.weights
            ss.weights = Weights(
                travel=st.slider("w₁ 이동 시간 T", 0.0, 2.0, w.travel, 0.1),
                confirm=st.slider("w₂ 승인 지연 C", 0.0, 2.0, w.confirm, 0.1),
                rejection=st.slider("w₃ 거절 위험 (1−A)", 0.0, 2.0, w.rejection, 0.1),
                load=st.slider("w₄ 병원 부하 L", 0.0, 2.0, w.load, 0.1),
                uncertainty=st.slider("w₅ 불확실성 U", 0.0, 2.0, w.uncertainty, 0.1),
            )
            if st.button("기본값으로", width="stretch"):
                ss.weights = Weights()
                st.rerun()

        st.divider()
        st.caption("⚠️ 합성 데이터 데모입니다. 실제 환자 데이터·병원 정보가 아니며 "
                   "임상 검증을 거치지 않았습니다. 최종 결정은 항상 사람이 합니다.")


def hour() -> int:
    return st.session_state.clock.hour


def next_case_id() -> str:
    st.session_state.case_seq += 1
    return f"A-{st.session_state.case_seq}"


def esc(text) -> str:
    return html.escape(str(text))


CSS = f"""
<style>
.sh-bar {{background:{NAVY};color:#fff;border-radius:10px;padding:14px 20px;display:flex;
  justify-content:space-between;align-items:center;margin-bottom:12px;}}
.sh-bar b {{font-size:1.15rem;letter-spacing:.04em}}
.sh-bar span {{font-size:.8rem;font-weight:700;letter-spacing:.06em;opacity:.9}}
.sh-case {{border:1px solid {GRID};border-radius:10px;padding:12px 16px;background:#fff;margin-bottom:10px}}
.sh-case .cid {{color:#2a78d6;font-weight:700;font-size:.8rem}}
.sh-case .title {{font-size:1.2rem;font-weight:700;color:{INK}}}
.sh-case .sub {{color:{INK2};font-size:.85rem}}
.sh-pill {{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.75rem;font-weight:700;
  border:1.5px solid;margin-left:6px;white-space:nowrap}}
.sh-card {{border:1.5px solid #c9d6e8;border-radius:10px;padding:12px 16px;margin-bottom:8px;background:#fff}}
.sh-card.top {{border-color:#1baf7a;background:#f1faf6}}
.sh-card .row {{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
.sh-rank {{display:inline-flex;width:28px;height:28px;border-radius:50%;background:#2a78d6;color:#fff;
  align-items:center;justify-content:center;font-weight:700;margin-right:10px;flex:none}}
.sh-card.top .sh-rank {{background:#0f7f6e}}
.sh-name {{font-weight:700;color:{INK}}}
.sh-reason {{color:{INK2};font-size:.85rem}}
.sh-eta {{text-align:right;font-size:.85rem;color:{INK};white-space:nowrap}}
.sh-eta b {{font-size:1rem}}
.sh-warn {{color:#a4510f;font-size:.8rem;margin-top:4px}}
.sh-why {{border:1.5px solid #e87ba4;background:#fdf3f7;border-radius:10px;padding:10px 14px;color:{INK}}}
.sh-why b {{color:#b0306a}}
.sh-esc {{border:2px solid {STATUS['critical']};background:#fdf1f1;border-radius:10px;padding:14px 16px;color:{INK}}}
.sh-esc b {{color:{STATUS['critical']}}}
.sh-tile {{border:1px solid {GRID};border-radius:10px;padding:10px 14px;background:#fff}}
.sh-tile .k {{font-size:.72rem;font-weight:700;color:{INK2};letter-spacing:.05em;text-transform:uppercase}}
.sh-tile .v {{font-size:1.8rem;font-weight:700;color:{INK};line-height:1.2}}
.sh-tile .s {{font-size:.75rem;color:{MUTED}}}
.sh-step {{border-radius:10px;padding:10px 12px;color:#fff;min-height:118px}}
.sh-step b {{display:block;margin-bottom:4px}}
.sh-step small {{opacity:.92}}
.sh-boundary {{border-left:4px solid {STATUS['critical']};background:#fdf6f2;padding:10px 14px;border-radius:6px;color:{INK}}}
mark.ev {{background:#fff1b8;padding:0 2px;border-radius:3px}}
@media (max-width: 640px) {{
  .sh-bar {{flex-direction:column;align-items:flex-start;gap:4px;padding:12px 14px}}
  .sh-bar b {{font-size:1rem}}
  .sh-case .title {{font-size:1.05rem}}
  .sh-card .row {{flex-direction:column;gap:6px}}
  .sh-eta {{text-align:left;white-space:normal;padding-left:38px}}
  .sh-tile .v {{font-size:1.5rem}}
  .sh-step {{min-height:0}}
}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def tile(label: str, value: str, sub: str = "", color: str = INK) -> str:
    return (f'<div class="sh-tile"><div class="k">{esc(label)}</div>'
            f'<div class="v" style="color:{color}">{esc(value)}</div>'
            f'<div class="s">{esc(sub)}</div></div>')


def plotly_layout(fig, height: int = 360, **kw):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="#fff", font_color=INK),
        **kw,
    )
    fig.update_xaxes(gridcolor=GRID, linecolor="#c3c2b7", zeroline=False, tickfont_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, linecolor="#c3c2b7", zeroline=False, tickfont_color=MUTED)
    return fig
