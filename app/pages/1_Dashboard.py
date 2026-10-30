from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from app.authentication import require_authenticated_tenant_context

st.set_page_config(page_title="Executive Dashboard", layout="wide")
context = require_authenticated_tenant_context()
st.title("Executive Dashboard")
st.caption(f"Company: {context.tenant_display_name}")
st.info("Dashboard foundation. KPI cards and evidence-backed explanations will be added after governed mappings are approved.")
