"""Profile: nickname plus the food conditions that steer recipe generation."""
import streamlit as st

import auth
import auth_ui
import db
import recipe

st.set_page_config(page_title="프로필", page_icon="👤")
user = auth_ui.require_login()
st.title("👤 프로필")

profile = db.get_profile(user["id"])
DIETS = ["없음", "채식", "저염", "저탄수화물", "고단백"]
with st.form("profile_form"):
    nickname = st.text_input("닉네임", value=profile["nickname"], max_chars=auth.MAX_NICKNAME)
    allergies = st.text_input("알레르기 재료 (쉼표로 구분)", value=", ".join(profile["allergies"]),
                              help="이 재료가 든 레시피는 추천에서 제외됩니다.")
    dislikes = st.text_input("기피 재료 (쉼표로 구분)", value=", ".join(profile["dislikes"]))
    diet = st.selectbox("선호 식단", DIETS,
                        index=DIETS.index(profile["diet"]) if profile["diet"] in DIETS else 0)
    if st.form_submit_button("저장"):
        nickname = nickname.strip()
        if not nickname:
            st.error("닉네임을 입력해 주세요.")
        else:
            split = lambda s: recipe.clean_list(s.split(","))  # noqa: E731
            db.update_profile(user["id"], nickname, split(allergies), split(dislikes),
                              None if diet == "없음" else diet)
            st.session_state["user"] = {**user, "nickname": nickname}
            st.success("프로필을 저장했습니다.")
