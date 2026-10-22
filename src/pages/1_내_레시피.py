"""Saved recipes: list, view and delete (own recipes only)."""
import streamlit as st

import auth_ui
import db

st.set_page_config(page_title="내 레시피", page_icon="📖")
user = auth_ui.require_login()
st.title("📖 내 레시피")

recipes = db.list_recipes(user["id"])
if not recipes:
    st.info("저장된 레시피가 없습니다. 메인 화면에서 레시피를 만들고 저장해 보세요.")
for r in recipes:
    with st.container(border=True):
        st.subheader(r["title"])
        st.caption(f"{r['servings']}인분 · {r['cook_time_min']}분 · 저장일 {r['created_at'][:10]}")
        if r["have"]:
            st.markdown("보유 재료: " + " ".join(f":green[{h}]" for h in r["have"]))
        if r["missing"]:
            st.markdown("부족한 재료: " + " ".join(f":red[{m}]" for m in r["missing"]))
        with st.expander("자세히 보기"):
            for i, step in enumerate(r["steps"], 1):
                st.write(f"{i}. {step}")
        if st.button("삭제", key=f"del_{r['id']}"):
            db.delete_recipe(user["id"], r["id"])
            st.rerun()
