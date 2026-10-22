"""Fridge photo -> ingredient list (step 1) -> recipes (step 2) -> save (step 3)."""
import time

import pandas as pd
import streamlit as st

import auth_ui
import db
import llm
import recipe
import vision

COOLDOWN_SEC = 5


def show_attempts(attempts):
    with st.expander("시도 기록"):
        st.markdown("\n".join(f"- {a}" for a in attempts) or "(없음)")


st.set_page_config(page_title="냉장고 레시피 추천", page_icon="🥬")
user = auth_ui.render_sidebar()
st.title("🥬 냉장고 레시피 추천")

try:
    secrets = st.secrets
    secrets.get("OPENROUTER_API_KEY")  # touches the file; raises if none exists
except Exception:
    secrets = None
key = llm.get_api_key(secrets)
if not key:
    st.error("OPENROUTER_API_KEY를 찾을 수 없습니다. .env 또는 Secrets를 확인해 주세요.")
    st.stop()
state = st.session_state

# ---------------------------------------------------------------- step 1
st.header("1단계 · 냉장고 사진에서 식재료 인식")
st.caption(f"이미지 모델: {vision.get_models(secrets)[0]}")
upload = st.file_uploader("냉장고 사진을 업로드하세요 (JPG/PNG/WebP, 5MB 이하)",
                          type=["jpg", "jpeg", "png", "webp"])


def start_list(names, model, attempts):
    state["result"] = vision.Recognition(names, model, attempts)
    # Explicit dtypes: an empty list would otherwise become float64 and break the text columns.
    state["ing_df"] = pd.DataFrame({
        "식재료": pd.Series(names, dtype="object"),
        "수량": pd.Series([1.0] * len(names), dtype="float64"),
        "단위": pd.Series(["개"] * len(names), dtype="object")})
    state["editor_n"] = state.get("editor_n", 0) + 1
    for k in ("gen", "gen_error"):
        state.pop(k, None)


if upload is not None:
    if upload.size > vision.MAX_UPLOAD_BYTES:
        st.error("파일이 5MB를 넘습니다. 더 작은 사진을 올려 주세요.")
        st.stop()
    st.image(upload, caption=upload.name, width="stretch")
    if st.button("식재료 인식하기", type="primary"):
        raw = upload.getvalue()
        with st.spinner("분석 중입니다. 무료 모델은 최대 1~2분 걸릴 수 있어요..."):
            try:
                small = vision.resize_image(raw)
                state["resize_info"] = f"이미지 축소: {len(raw) // 1024}KB → {len(small) // 1024}KB"
                res = vision.recognize(raw, key, models=vision.get_models(secrets))
                start_list(res.ingredients, res.model, res.attempts)
                state.pop("rec_error", None)
            except llm.LLMError as e:
                # Wipe the previous result so it can't pass for this photo's result.
                for k in ("result", "ing_df", "gen", "gen_error"):
                    state.pop(k, None)
                state["rec_error"] = (str(e), e.attempts)

if state.get("rec_error"):
    message, attempts = state["rec_error"]
    st.error(f"❌ 식재료 인식에 실패했습니다. {message}")
    show_attempts(attempts)
    if st.button("재료를 직접 입력할게요"):
        state.pop("rec_error", None)
        start_list([], "수동 입력", [])
        st.rerun()

result = state.get("result") if "ing_df" in state else None  # never render half a state
confirmed = []
if result:
    if state.get("resize_info"):
        st.caption(state["resize_info"])
    st.success(f"식재료 목록 준비됨 — 사용한 모델: {result.model}")
    show_attempts(result.attempts)
    if not result.ingredients:
        st.warning("식재료가 없습니다. 아래 표에서 직접 추가할 수 있어요.")
    left, right = st.columns([5, 1])
    left.markdown("**인식된 식재료** — 이름·수량·단위를 고치거나 행을 삭제/추가하세요.")
    if right.button("모두 삭제"):
        state["ing_df"] = state["ing_df"].iloc[0:0]
        state["editor_n"] += 1
        st.rerun()
    edited = st.data_editor(
        state["ing_df"], num_rows="dynamic", width="stretch",
        key=f"editor_{state['editor_n']}",
        column_config={
            "식재료": st.column_config.TextColumn("식재료", max_chars=recipe.MAX_TEXT_LEN),
            "수량": st.column_config.NumberColumn("수량", min_value=0.0, step=1.0, default=1.0),
            "단위": st.column_config.SelectboxColumn("단위", options=recipe.UNITS, default="개"),
        })
    for _, row in edited.iterrows():
        name = recipe.clean_text(row["식재료"]) if pd.notna(row["식재료"]) else ""
        if name:
            qty = float(row["수량"]) if pd.notna(row["수량"]) else 1.0
            unit = row["단위"] if pd.notna(row["단위"]) else "개"
            confirmed.append({"name": name, "quantity": qty, "unit": unit})
    confirmed = confirmed[:recipe.MAX_ITEMS]
    st.write(f"확정된 식재료 {len(confirmed)}개")

# ---------------------------------------------------------------- step 2
if result:
    st.header("2단계 · 레시피 추천")
    if confirmed:
        st.write("🥕 " + ", ".join(recipe.describe_ingredient(i) for i in confirmed))
    profile = db.get_profile(user["id"]) if user else {}
    if profile and (profile["allergies"] or profile["dislikes"] or profile["diet"]):
        st.caption("프로필 조건 반영: " + " / ".join(filter(None, [
            f"알레르기 {', '.join(profile['allergies'])}" if profile["allergies"] else "",
            f"기피 {', '.join(profile['dislikes'])}" if profile["dislikes"] else "",
            f"식단 {profile['diet']}" if profile["diet"] else ""])))
    elif not user:
        st.caption("로그인하면 프로필의 알레르기·기피 재료가 추천에 반영돼요.")
    c1, c2, c3, c4 = st.columns(4)
    options = {"kind": c1.selectbox("종류", recipe.KINDS),
               "level": c2.selectbox("난이도", recipe.LEVELS),
               "time": c3.selectbox("조리 시간", recipe.TIMES),
               "servings": c4.selectbox("인원", recipe.SERVINGS, index=1,
                                         format_func=lambda n: f"{n}인분")}
    label = "다시 추천받기" if state.get("gen") or state.get("gen_error") else "레시피 추천받기"
    if st.button(label, type="primary", disabled=not confirmed):
        wait = COOLDOWN_SEC - (time.time() - state.get("last_gen_at", 0))
        if wait > 0:
            st.warning(f"무료 모델 보호를 위해 {int(wait) + 1}초 뒤에 다시 눌러 주세요.")
        else:
            with st.spinner("레시피를 만드는 중입니다. 최대 1~2분 걸릴 수 있어요..."):
                try:
                    state["gen"] = recipe.generate(
                        confirmed, key, profile, options, models=recipe.get_models(secrets))
                    state.pop("gen_error", None)
                    state.pop("saved_titles", None)
                except llm.LLMError as e:
                    state.pop("gen", None)  # never show an older result as this one
                    state["gen_error"] = (str(e), e.attempts)
            state["last_gen_at"] = time.time()

    if state.get("gen_error"):
        message, attempts = state["gen_error"]
        st.error(f"❌ 레시피를 만들지 못했습니다. {message}")
        show_attempts(attempts)
    gen = state.get("gen")
    if gen:
        st.success(f"레시피 {len(gen.recipes)}개 — 사용한 모델: {gen.model}")
        saved = state.setdefault("saved_titles", set())
        for i, r in enumerate(gen.recipes):
            with st.container(border=True):
                st.subheader(r["title"])
                st.caption(f"{r['servings']}인분 · {r['cook_time_min']}분")
                if r["have"]:
                    st.markdown("보유 재료: " + " ".join(f":green[{h}]" for h in r["have"]))
                if r["missing"]:
                    st.markdown("부족한 재료: " + " ".join(f":red[{m}]" for m in r["missing"]))
                else:
                    st.markdown("부족한 재료: 없음 ✅")
                with st.expander("자세히 보기"):
                    for n, step in enumerate(r["steps"], 1):
                        st.write(f"{n}. {step}")
                if r["title"] in saved:
                    st.success("✅ 저장했습니다. '내 레시피' 페이지에서 볼 수 있어요.")
                elif st.button("레시피 저장", key=f"save_{i}"):
                    if not user:
                        st.warning("저장하려면 먼저 사이드바에서 로그인해 주세요.")
                    else:
                        db.save_recipe(user["id"], r)
                        saved.add(r["title"])
                        st.rerun()
