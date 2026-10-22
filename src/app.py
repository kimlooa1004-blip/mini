"""Step 1 UI: upload a fridge photo, recognise ingredients, edit the list."""
import pandas as pd
import streamlit as st

import vision

st.set_page_config(page_title="냉장고 식재료 인식", page_icon="🥬")
st.title("🥬 냉장고 식재료 인식 (1단계)")

primary, _ = vision.get_models()
st.caption(f"기본 모델: {primary}")

try:
    secrets = st.secrets
    secrets.get("OPENROUTER_API_KEY")  # touches the file; raises if none exists
except Exception:
    secrets = None
key = vision.get_api_key(secrets)
if not key:
    st.error("OPENROUTER_API_KEY를 찾을 수 없습니다. .env 또는 Secrets를 확인해 주세요.")
    st.stop()

upload = st.file_uploader("냉장고 사진을 업로드하세요", type=["jpg", "jpeg", "png", "webp"])
if upload is not None:
    if upload.size > vision.MAX_UPLOAD_BYTES:
        st.error("파일이 5MB를 넘습니다. 더 작은 사진을 올려 주세요.")
        st.stop()
    st.image(upload, caption=upload.name, use_container_width=True)

    if st.button("식재료 인식하기", type="primary"):
        raw = upload.getvalue()
        with st.spinner("분석 중입니다. 무료 모델은 최대 1~2분 걸릴 수 있어요..."):
            try:
                small = vision.resize_image(raw)
                st.info(f"이미지 축소: {len(raw) // 1024}KB → {len(small) // 1024}KB")
                st.session_state["result"] = vision.recognize(raw, key)
            except vision.VisionError as e:
                st.session_state.pop("result", None)
                st.error(str(e))
                with st.expander("시도 기록"):
                    st.write(e.attempts or ["(없음)"])

result = st.session_state.get("result")
if result:
    st.success(f"인식 완료 — 사용한 모델: {result.model}")
    with st.expander("시도 기록"):
        st.write(result.attempts)
    if not result.ingredients:
        st.warning("식재료를 찾지 못했습니다. 아래에서 직접 추가할 수 있어요.")
    edited = st.data_editor(
        pd.DataFrame({"식재료": result.ingredients}),
        num_rows="dynamic", use_container_width=True, key="editor")
    confirmed = [n.strip() for n in edited["식재료"].dropna() if n and n.strip()]
    st.session_state["confirmed_ingredients"] = confirmed
    st.write(f"확정된 식재료 {len(confirmed)}개")
    st.button("레시피 추천받기 (2단계에서 연결)", disabled=True)
