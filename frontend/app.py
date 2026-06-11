"""FastPilot frontend (Streamlit) — Phase 0 placeholder.

Phase 2 builds the real UI per the approved design (mocks + System file): welcome
state, Chat/Agent/Playground modes, SSE streaming, sources, feedback. For now this
is a valid entrypoint so the image builds and the skeleton is coherent.
"""

import os

import streamlit as st

st.set_page_config(page_title="FastPilot", page_icon="⚡", layout="centered")

st.title("⚡ FastPilot")
st.caption("Learn FastAPI, fast. — frontend scaffold (Phase 0)")
st.info("UI lands in Phase 2. Backend: " + os.environ.get("API_BASE_URL", "http://localhost:8000"))
