"""SYNAPSE-H Transfer Orchestrator — Streamlit entry point.

Run from the repository root:  streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import common  # noqa: E402

st.set_page_config(page_title="SYNAPSE-H", page_icon="🚑", layout="wide")
common.init_state()
common.inject_css()
common.require_login()

VIEWS = Path(__file__).parent / "views"
pages = {
    "SYNAPSE-H": [
        st.Page(VIEWS / "home.py", title="개요", icon="🏠", default=True),
    ],
    "운영 (Operations)": [
        st.Page(VIEWS / "orchestrator.py", title="전원 오케스트레이터", icon="🚑"),
        st.Page(VIEWS / "command.py", title="지역 상황실", icon="🗺️"),
        st.Page(VIEWS / "allocation.py", title="다중 환자 동시 배정", icon="🧮"),
        st.Page(VIEWS / "live_data.py", title="공공 데이터 연동", icon="📡"),
    ],
    "검증·거버넌스 (Evidence)": [
        st.Page(VIEWS / "twin.py", title="합성 디지털 트윈", icon="🧪"),
        st.Page(VIEWS / "audit.py", title="감사 로그 · 안전", icon="🛡️"),
        st.Page(VIEWS / "business.py", title="시장 · 사업 모델", icon="📈"),
    ],
}
nav = st.navigation(pages)
common.sidebar()
nav.run()
