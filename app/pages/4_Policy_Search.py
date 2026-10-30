from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from app.authentication import require_authenticated_tenant_context

st.set_page_config(page_title="Policy Search", layout="wide")
context = require_authenticated_tenant_context()
st.title("Policy Search")
st.caption(f"Company: {context.tenant_display_name}")
if not context.has_permission("policy.view"):
    st.error("Your active company role does not grant policy.view.")
    st.stop()
st.info("Policy search will retrieve only documents the active company membership is allowed to access.")
