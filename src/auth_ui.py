"""Sidebar log-in / sign-up widget shared by every page."""
import streamlit as st

import auth


def current_user():
    return st.session_state.get("user")


def render_sidebar():
    """Draw the account box and return the logged-in user dict (or None)."""
    with st.sidebar:
        user = current_user()
        if user:
            st.markdown(f"👤 **{user['nickname']}**님")
            st.caption(user["email"])
            if st.button("로그아웃"):
                for key in ("user", "saved_titles"):
                    st.session_state.pop(key, None)
                st.rerun()
            return user
        st.subheader("계정")
        tab_in, tab_up = st.tabs(["로그인", "회원가입"])
        with tab_in, st.form("login_form"):
            email = st.text_input("이메일", key="login_email")
            password = st.text_input("비밀번호", type="password", key="login_pw")
            if st.form_submit_button("로그인"):
                try:
                    st.session_state["user"] = auth.login(email, password)
                except auth.AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
        with tab_up, st.form("signup_form"):
            email = st.text_input("이메일", key="signup_email")
            nickname = st.text_input("닉네임", key="signup_nick")
            password = st.text_input("비밀번호 (8자 이상)", type="password", key="signup_pw")
            if st.form_submit_button("회원가입"):
                try:
                    st.session_state["user"] = auth.signup(email, password, nickname)
                except auth.AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
    return None


def require_login():
    user = render_sidebar()
    if user is None:
        st.info("로그인이 필요한 화면입니다. 왼쪽 사이드바에서 로그인하거나 가입해 주세요.")
        st.stop()
    return user
