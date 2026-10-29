from __future__ import annotations

import streamlit as st

from src.config.settings import get_settings

settings = get_settings()

st.set_page_config(
    page_title=settings.app_name,
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("✈️ Airline Contact Center AI Platform")
st.caption("Project foundation · Local-first · Modular monolith")

st.info(
    "The foundation is running. No database connection or schema mutation is "
    "performed by this page. We will add those in a separate, tested step."
)

left, right = st.columns(2)
with left:
    st.subheader("Platform modules")
    st.markdown(
        "- Executive Dashboard — planned\n"
        "- Chat Assistant — planned\n"
        "- Forecasting — planned\n"
        "- Policy Search — planned"
    )
with right:
    st.subheader("Language boundaries")
    st.markdown(
        "- **Employee language:** controls the assistant's answer language.\n"
        "- **Service language:** describes the passenger/contact/queue context.\n"
        "- **Policy document language:** records the source language of a policy."
    )

st.divider()
st.caption(f"Environment: {settings.app_env} · Configuration loaded without exposing secrets")
