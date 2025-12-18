import os
import hashlib
import streamlit as st

def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def require_login():
    admin_user = os.environ.get("JOBTRACKER_USER", "")
    admin_pass_hash = os.environ.get("JOBTRACKER_PASS_SHA256", "")

    if not admin_user or not admin_pass_hash:
        st.error(
            "Auth not configured. Set env vars:\n"
            "- JOBTRACKER_USER\n"
            "- JOBTRACKER_PASS_SHA256\n\n"
            "Hash example:\n"
            "python -c \"import hashlib; print(hashlib.sha256('mypassword'.encode()).hexdigest())\""
        )
        st.stop()

    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if st.session_state.auth_ok:
        return

    st.title("Job Tracker — Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login"):
        if u == admin_user and _hash(p) == admin_pass_hash:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.stop()

def logout_button():
    if st.button("Logout"):
        st.session_state.auth_ok = False
        st.rerun()
