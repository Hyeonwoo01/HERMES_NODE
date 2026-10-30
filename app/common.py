"""Shared session state, sidebar controls and styling for every page."""

from __future__ import annotations

import html
from datetime import time

import streamlit as st

from synapse_h.audit import AuditLog
from synapse_h.audit_store import SQLiteAuditStore
from synapse_h.auth import DEMO_PERMISSIONS, ROLE_LABELS, User, UserStore
from synapse_h.data import CONCURRENT_CASES, default_network, origins
from synapse_h.intake import RuleBasedExtractor, build_case
from synapse_h.llm import LLMClient, LLMConfig
from synapse_h.llm_intake import LLMExtractor
from synapse_h.optimizer import TERM_LABELS, Weights

# Warm editorial design tokens (cream canvas, ink, signal orange).
CANVAS, LIFTED, WHITE = "#F3F0EE", "#FCFBFA", "#FFFFFF"
INK, INK2, MUTED, DUST = "#141413", "#262627", "#696969", "#D1CDC7"
SIGNAL, SIGNAL_LIGHT, CLAY, LINK = "#CF4500", "#F37338", "#9A3A0A", "#3860BE"
GHOST, GRID, HAIRLINE = "#E8E2DA", "#E2DDD7", "rgba(20,20,19,0.10)"
# Chart categorical slots in fixed order, validated on the cream canvas (CVD + contrast).
SERIES = [LINK, SIGNAL_LIGHT, "#1F8A70", "#C99000", CLAY]
STATUS = {"good": "#1F7A4D", "warning": "#C99000", "serious": SIGNAL_LIGHT, "critical": "#C2361C"}
TERM_COLORS = dict(zip(TERM_LABELS, SERIES))
FONT = "'Sofia Sans', 'Noto Sans KR', sans-serif"

def secrets() -> dict:
    """Deployment secrets (.streamlit/secrets.toml or Streamlit Cloud). Empty when none are set."""
    try:
        return {k: st.secrets[k] for k in st.secrets}
    except Exception:  # no secrets file: public demo
        return {}


@st.cache_resource
def _audit_store(path: str) -> SQLiteAuditStore:
    return SQLiteAuditStore(path)


@st.cache_resource
def user_store() -> UserStore:
    """One store per server process, so failed-login lockouts apply across browser sessions."""
    return UserStore.from_mapping(dict(secrets().get("auth", {})).get("users", {}))


def llm_extractor() -> LLMExtractor | None:
    """The LLM extractor when a key is configured, else None (rule-based only)."""
    cfg = LLMConfig.from_mapping(secrets())
    return None if cfg.missing else LLMExtractor(LLMClient(cfg))


def extract(note: str, use_llm: bool):
    ex = llm_extractor() if use_llm else None
    return (ex or RuleBasedExtractor()).extract(note)


def make_audit() -> AuditLog:
    """Session audit log, persisted to SQLite when AUDIT_DB_PATH is set in the secrets."""
    path = str(secrets().get("AUDIT_DB_PATH", "")).strip()
    return AuditLog.from_store(_audit_store(path)) if path else AuditLog()


def init_state() -> None:
    ss = st.session_state
    if "network" not in ss:
        ss.network = default_network()
    if "origins" not in ss:
        ss.origins = origins()
    ss.setdefault("data_source", "synthetic")
    if "audit" not in ss:
        ss.audit = make_audit()
    if "concurrent" not in ss:
        ss.concurrent = [build_case(d["case_id"], d["origin_id"], d) for d in CONCURRENT_CASES]
    ss.setdefault("case_seq", 1060)
    ss.setdefault("mode", "visible")
    ss.setdefault("clock", time(14, 32))
    ss.setdefault("user", "전원 간호사 김OO")
    ss.setdefault("weights", Weights())
    ss.setdefault("current_user", None)


def auth_enabled() -> bool:
    return user_store().enabled


def current_user() -> User:
    ss = st.session_state
    if auth_enabled():
        return ss.current_user
    return User("demo", ss.user, "supervisor")


def can(permission: str) -> bool:
    if not auth_enabled():
        return permission in DEMO_PERMISSIONS
    u = st.session_state.current_user
    return bool(u and u.can(permission))


def require_login() -> None:
    """Stop the page with a login form when accounts are configured and nobody is signed in."""
    ss = st.session_state
    store = user_store()
    if not store.enabled or ss.current_user is not None:
        return
    st.markdown("### SYNAPSE-H 로그인")
    st.caption("권한이 있는 의료진 계정으로 로그인하세요. 계정은 배포 환경의 Secrets에서 관리됩니다.")
    with st.form("login"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("로그인", type="primary")
    if ok:
        if store.locked(username):
            st.error("로그인 실패가 반복되어 5분 동안 잠겼습니다.")
        else:
            user = store.authenticate(username, password)
            if user is None:
                st.error("아이디 또는 비밀번호가 맞지 않습니다.")
            else:
                ss.current_user = user
                ss.user = user.display_name
                ss.audit.system_event("login", user=user.username, role=user.role)
                st.rerun()
    st.stop()


def synthetic_only(page: str) -> None:
    """Pages built around the synthetic region stop when another hospital list is loaded."""
    if st.session_state.get("data_source", "synthetic") != "synthetic":
        st.info(f"{page}은(는) 합성 지역 네트워크용 데모입니다. '공공 데이터 연동' 화면에서 합성 네트워크로 되돌리면 볼 수 있습니다.")
        st.stop()


def denied(permission_label: str) -> None:
    u = current_user()
    st.warning(f"현재 권한({ROLE_LABELS.get(u.role, u.role)})으로는 {permission_label}을(를) 할 수 없습니다.")


def sidebar() -> None:
    ss = st.session_state
    locked = not can("change_settings")
    with st.sidebar:
        st.markdown("### ⚙️ 운영 설정")
        mode = st.radio(
            "운영 모드",
            ["visible", "shadow"],
            format_func=lambda m: {"visible": "추천 표시 (데모)",
                                   "shadow": "Shadow · 결정 후 공개 (데모)"}[m],
            index=0 if ss.mode == "visible" else 1,
            disabled=locked,
            help="Shadow mode에서는 사용자가 먼저 병원을 선택한 뒤 추천이 공개되어 "
                 "진료에 영향을 주지 않고 성능을 비교합니다 (제안서 §4.3 Stage 3).",
        )
        ss.mode = mode
        if auth_enabled():
            u = current_user()
            st.markdown(f"**{esc(u.display_name)}** · {ROLE_LABELS.get(u.role, u.role)}")
            if st.button("로그아웃", width="stretch"):
                ss.audit.system_event("logout", user=u.username)
                ss.current_user = None
                st.rerun()
        else:
            ss.user = st.text_input("사용자 (공개 데모 · 로그인 미설정)", ss.user)
        ss.clock = st.time_input("시뮬레이션 시각", ss.clock, step=60 * 30)

        with st.expander("⚖️ 추천 기준 중요도", expanded=False):
            if not can("change_settings"):
                st.caption("감독자만 바꿀 수 있습니다.")
            st.caption("병원 순위를 매길 때 각 기준을 얼마나 중요하게 볼지 조절합니다. 1.0이 기본값입니다.")
            w = ss.weights
            ss.weights = Weights(
                travel=st.slider("이동 시간", 0.0, 2.0, w.travel, 0.1, disabled=locked),
                confirm=st.slider("승인 대기 시간", 0.0, 2.0, w.confirm, 0.1, disabled=locked),
                rejection=st.slider("거절 위험", 0.0, 2.0, w.rejection, 0.1, disabled=locked),
                load=st.slider("병원 혼잡도", 0.0, 2.0, w.load, 0.1, disabled=locked),
                uncertainty=st.slider("데이터 불확실성", 0.0, 2.0, w.uncertainty, 0.1, disabled=locked),
            )
            if st.button("기본값으로", width="stretch", disabled=locked):
                ss.weights = Weights()
                st.rerun()

        st.divider()
        if ss.get("data_source") == "live":
            st.caption("⚠️ 병원 병상·역량은 공공데이터, 수용률·응답 시간은 가정값입니다. 실제 환자 데이터가 아니며 "
                       "임상 검증을 거치지 않았습니다. 최종 결정은 항상 사람이 합니다.")
        else:
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
@import url("https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@100..900&display=swap");
h1, h2, h3, h4 {{letter-spacing:-0.02em}}
[data-testid="stAppViewContainer"] .block-container {{padding-top:2.5rem}}

/* Floating pill navigation header */
.sh-nav {{background:{WHITE};border-radius:999px;box-shadow:rgba(0,0,0,0.04) 0 4px 24px 0;
  padding:14px 32px;display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 28px}}
.sh-nav .brand {{display:flex;align-items:center;gap:14px;min-width:0}}
.sh-nav .logo {{font-weight:700;font-size:1rem;letter-spacing:-0.01em;color:{INK};white-space:nowrap}}
.sh-nav .logo i {{display:inline-block;width:10px;height:10px;border-radius:50%;background:{SIGNAL};
  margin-right:8px;vertical-align:1px}}
.sh-nav .ttl {{font-weight:500;font-size:1rem;letter-spacing:-0.03em;color:{INK2};white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}}
.sh-nav .sep {{width:1px;height:20px;background:{DUST}}}
.sh-nav {{margin-bottom:10px}}
.sh-demo {{background:#FBE7DC;color:{CLAY};border-radius:999px;padding:8px 20px;font-size:.8rem;font-weight:500;
  line-height:1.4;margin:0 0 24px}}

/* Eyebrow label: accent dot + uppercase tracking (the only uppercase in the system) */
.sh-eyebrow {{font-size:.8rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:{INK2};
  white-space:nowrap}}
.sh-eyebrow::before {{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
  background:{SIGNAL};margin-right:8px;vertical-align:2px}}

/* Case header + cards */
.sh-case {{border-radius:32px;padding:24px 28px;background:{LIFTED};margin-bottom:16px}}
.sh-case .title {{font-size:1.5rem;font-weight:500;letter-spacing:-0.02em;color:{INK};line-height:1.2;margin:8px 0 6px}}
.sh-case .sub {{color:{MUTED};font-size:.9rem;line-height:1.5}}
.sh-pill {{display:inline-block;border-radius:999px;padding:3px 12px;font-size:.72rem;font-weight:700;
  letter-spacing:.04em;border:1.5px solid;margin-left:8px;white-space:nowrap;vertical-align:4px}}
.sh-card {{border-radius:32px;padding:20px 24px;margin-bottom:12px;background:{LIFTED};border:1px solid {HAIRLINE}}}
.sh-card.top {{background:{WHITE};border:1.5px solid {INK};box-shadow:rgba(0,0,0,0.08) 0 24px 48px 0}}
.sh-card .row {{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}}
.sh-rank {{display:inline-flex;width:40px;height:40px;border-radius:50%;background:{WHITE};color:{INK};
  border:1.5px solid {INK};align-items:center;justify-content:center;font-weight:500;font-size:1.05rem;
  margin-right:14px;flex:none}}
.sh-card.top .sh-rank {{background:{INK};color:{CANVAS}}}
.sh-name {{font-weight:500;font-size:1.15rem;letter-spacing:-0.02em;color:{INK}}}
.sh-name small {{color:{MUTED};font-weight:450;font-size:.78rem;letter-spacing:0;margin-left:6px}}
.sh-reason {{color:{MUTED};font-size:.9rem;line-height:1.45;margin-top:2px}}
.sh-eta {{text-align:right;font-size:.88rem;color:{INK2};white-space:nowrap;line-height:1.6}}
.sh-eta b {{font-size:1.05rem;font-weight:500;color:{INK}}}
.sh-eta .muted {{color:{MUTED}}}
.sh-warn {{color:{CLAY};font-size:.82rem;margin-top:6px}}

.sh-why {{background:{WHITE};border-radius:32px;padding:18px 24px;color:{INK};line-height:1.5}}
.sh-why .sh-eyebrow {{display:block;margin-bottom:6px}}
.sh-esc {{background:{INK};color:{CANVAS};border-radius:32px;padding:22px 28px;line-height:1.55}}
.sh-esc .sh-eyebrow {{display:block;color:{SIGNAL_LIGHT};margin-bottom:6px}}
.sh-esc .sh-eyebrow::before {{background:{SIGNAL_LIGHT}}}

/* Stat tiles */
.sh-tile {{border-radius:32px;padding:20px 24px;background:{LIFTED};height:100%}}
.sh-tile .k {{font-size:.72rem;font-weight:700;color:{INK2};letter-spacing:.04em;text-transform:uppercase}}
.sh-tile .k::before {{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
  background:{SIGNAL};margin-right:7px;vertical-align:2px}}
.sh-tile .v {{font-size:2.25rem;font-weight:500;letter-spacing:-0.02em;color:{INK};line-height:1.15;margin-top:6px}}
.sh-tile .s {{font-size:.8rem;color:{MUTED}}}

/* Home: hero, orbit steps, portrait links, footer */
.sh-hero {{position:relative;padding:8px 0 24px;overflow:hidden}}
.sh-hero .ghost {{position:absolute;right:-8px;top:-18px;font-size:clamp(72px,12vw,150px);font-weight:500;
  letter-spacing:-0.04em;color:{GHOST};line-height:1;z-index:0;pointer-events:none;user-select:none}}
.sh-hero .sh-eyebrow {{position:relative;z-index:1}}
.sh-hero h1 {{position:relative;z-index:1;font-size:clamp(2.2rem,5vw,4rem);font-weight:500;line-height:1.05;
  letter-spacing:-0.02em;margin:14px 0 18px;padding:0;max-width:16ch}}
.sh-hero p {{position:relative;z-index:1;font-size:1.05rem;line-height:1.55;color:{INK2};max-width:56ch}}
.sh-steps {{position:relative;display:flex;justify-content:space-between;gap:12px;margin:20px 0 8px}}
.sh-steps svg {{position:absolute;left:0;top:0;width:100%;height:90px;z-index:0;overflow:visible}}
.sh-step {{position:relative;z-index:1;flex:1;text-align:center;min-width:0}}
.sh-step .orb {{width:88px;height:88px;border-radius:50%;margin:0 auto 12px;display:flex;align-items:center;
  justify-content:center;background:{WHITE};border:1.5px solid {INK};font-size:1.6rem;font-weight:500;color:{INK}}}
.sh-step:nth-child(even) {{margin-top:34px}}
.sh-step b {{display:block;font-weight:500;font-size:1.05rem;letter-spacing:-0.02em}}
.sh-step small {{display:block;color:{MUTED};font-size:.85rem;line-height:1.4;padding:0 6px}}
.sh-orbits {{display:flex;flex-wrap:wrap;gap:28px 48px;justify-content:center;margin:12px auto;max-width:760px}}
.sh-portrait {{position:relative;width:200px;text-decoration:none!important;color:{INK}!important}}
.sh-portrait:nth-child(3n+2) {{margin-top:48px}}
.sh-portrait .disc {{width:168px;height:168px;border-radius:50%;margin:0 auto;display:flex;align-items:center;
  justify-content:center;font-size:3.2rem;background:{WHITE};box-shadow:rgba(0,0,0,0.08) 0 24px 48px 0;position:relative}}
.sh-portrait .sat {{position:absolute;right:6px;bottom:4px;width:52px;height:52px;border-radius:50%;background:{INK};
  color:{CANVAS};display:flex;align-items:center;justify-content:center;font-size:1.3rem}}
.sh-portrait .sh-eyebrow {{display:block;text-align:center;margin-top:16px;font-size:.7rem}}
.sh-portrait b {{display:block;text-align:center;font-weight:500;font-size:1.2rem;letter-spacing:-0.02em;margin-top:4px}}
.sh-portrait small {{display:block;text-align:center;color:{MUTED};font-size:.84rem;line-height:1.4;margin-top:4px}}
.sh-footer {{background:{INK};color:{CANVAS};border-radius:40px;padding:48px 44px 40px;margin-top:40px}}
.sh-footer h2 {{color:{CANVAS}!important;font-weight:500;font-size:clamp(1.6rem,3vw,2.25rem);
  letter-spacing:-0.02em;line-height:1.2;margin:0 0 28px;padding:0;max-width:32ch}}
.sh-footer .cols {{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}}
.sh-footer .h {{font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#A39E98;margin-bottom:8px}}
.sh-footer p {{font-size:.88rem;line-height:1.55;color:{CANVAS};margin:0}}
.sh-footer .rule {{height:1px;background:rgba(255,255,255,0.18);margin:32px 0 16px}}
.sh-footer .fine {{font-size:.78rem;color:#A39E98}}
.sh-boundary {{background:{LIFTED};border-radius:32px;padding:22px 28px;color:{INK};line-height:1.55}}
.sh-boundary .sh-eyebrow {{display:block;margin-bottom:6px}}
mark.ev {{background:#F9D9C5;padding:1px 4px;border-radius:6px;color:{INK}}}

/* Streamlit widgets: ink pill primary, outlined pill secondary */
[data-testid^="stBaseButton-primary"] {{background:{INK}!important;border:1.5px solid {INK}!important;
  color:{CANVAS}!important}}
[data-testid^="stBaseButton-primary"] p {{color:{CANVAS}!important;font-weight:500;letter-spacing:-0.02em}}
[data-testid^="stBaseButton-secondary"] {{background:{WHITE}!important;border:1.5px solid {INK}!important;
  color:{INK}!important}}
[data-testid^="stBaseButton-secondary"] p {{font-weight:500;letter-spacing:-0.02em}}
[data-testid^="stBaseButton"]:active {{transform:translateY(1px)}}
[data-testid="stExpander"] details {{border-radius:24px;background:{LIFTED}}}
[data-testid="stAlert"] > div {{border-radius:24px}}
[data-testid="stForm"] {{border-radius:32px;background:{LIFTED};padding:24px}}
[data-testid="stDataFrame"], [data-testid="stTable"] {{border-radius:20px;overflow:hidden}}

@media (max-width: 767px) {{
  .sh-nav {{padding:12px 20px;border-radius:28px;flex-wrap:wrap;gap:6px 12px}}
  .sh-demo {{border-radius:18px;padding:8px 14px}}
  .sh-nav .ttl {{font-size:.92rem}}
  .sh-nav .sep {{display:none}}
  .sh-case {{padding:20px}}
  .sh-case .title {{font-size:1.2rem}}
  .sh-card {{padding:18px 20px;border-radius:28px}}
  .sh-card .row {{flex-direction:column;gap:8px}}
  .sh-eta {{text-align:left;white-space:normal;padding-left:54px}}
  .sh-tile .v {{font-size:1.75rem}}
  .sh-steps {{flex-direction:column;gap:18px}}
  .sh-steps svg {{display:none}}
  .sh-step {{display:flex;align-items:center;gap:16px;text-align:left}}
  .sh-step:nth-child(even) {{margin-top:0}}
  .sh-step .orb {{width:56px;height:56px;margin:0;flex:none;font-size:1.2rem}}
  .sh-step small {{padding:0}}
  .sh-portrait:nth-child(3n+2) {{margin-top:0}}
  .sh-portrait {{width:150px}}
  .sh-portrait .disc {{width:132px;height:132px;font-size:2.6rem}}
  .sh-portrait .sat {{width:44px;height:44px;font-size:1.1rem}}
  .sh-footer {{padding:36px 24px 28px;border-radius:32px}}
  .sh-footer .cols {{grid-template-columns:1fr}}
}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


DEMO_WARNING = ("합성 데이터 데모 · 병원·환자·수용 점수는 가상 예시이며 검증되지 않았습니다 · "
                "실제 환자 정보를 입력하지 마세요 · 실제 진료 결정에 사용 금지")
LIVE_WARNING = ("공공데이터 병상·역량 + 가정값(수용률·응답 시간) · 수용 점수는 검증되지 않았습니다 · "
                "실제 환자 정보를 입력하지 마세요 · 실제 진료 결정에 사용 금지")


def demo_warning() -> str:
    return LIVE_WARNING if st.session_state.get("data_source") == "live" else DEMO_WARNING


def header(title: str, tag: str) -> None:
    """Floating pill navigation header plus the always-visible demo warning."""
    st.markdown(
        f'<div class="sh-nav"><div class="brand"><span class="logo"><i></i>SYNAPSE-H</span>'
        f'<span class="sep"></span><span class="ttl">{esc(title)}</span></div>'
        f'<span class="sh-eyebrow">{esc(tag)}</span></div>'
        f'<div class="sh-demo" role="note">⚠ {esc(demo_warning())}</div>', unsafe_allow_html=True)


def tile(label: str, value: str, sub: str = "", color: str = INK) -> str:
    return (f'<div class="sh-tile"><div class="k">{esc(label)}</div>'
            f'<div class="v" style="color:{color}">{esc(value)}</div>'
            f'<div class="s">{esc(sub)}</div></div>')


def plotly_layout(fig, height: int = 360, **kw):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=48, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=INK, size=13),
        title_font=dict(family=FONT, size=16, color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor=WHITE, font_color=INK, font_family=FONT, bordercolor=DUST),
        **kw,
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=DUST, zeroline=False, tickfont_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, linecolor=DUST, zeroline=False, tickfont_color=MUTED)
    return fig
