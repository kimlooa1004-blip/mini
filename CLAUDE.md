# Project notes

냉장고 사진에서 식재료를 인식하고 레시피를 추천하는 Streamlit 웹앱. 모델은 OpenRouter를 거쳐 호출한다.
기능 요구사항은 `docs/PRD_step1.md` ~ `docs/PRD_step3.md`, 구현과 PRD의 차이는 `docs/IMPLEMENTATION_NOTES.md`.

## 폴더 구조
- `docs/` — 제품 요구사항(PRD), 구현 노트, 보안 점검 결과
- `src/` — 앱 코드. `app.py`(1·2단계 화면), `pages/`(내 레시피, 프로필), `llm.py`(호출·재시도·폴백),
  `vision.py`(사진 인식), `recipe.py`(레시피 생성), `db.py`·`auth.py`·`auth_ui.py`(저장·로그인)
- `tests/` — 단위 테스트(`python -m unittest discover -s tests`)와 가짜 OpenRouter 서버 기반 화면 시험(`capture.py`)
- `scripts/` — `test_openrouter.py`(키·모델 실제 호출 시험), `install-hooks.sh`, `apply-tags.sh`
- `screenshot/` — 화면 캡처
- 루트 — `.env`(비밀 키, 커밋 금지), `.env.example`(템플릿), `.gitignore`, `requirements.txt`

## API keys
- The OpenRouter key lives in `.env` as `OPENROUTER_API_KEY` (gitignored; template in `.env.example`).
- Always load it from the environment variable. Never hardcode keys, print them, or commit them.
- 배포하면 `.env` 대신 Streamlit Community Cloud의 Settings › Secrets에 넣는다. `.streamlit/secrets.toml`도 커밋 금지.
- Enable the secret guard once per clone: `sh scripts/install-hooks.sh` (`.env`, `secrets.toml`, `sk-or-` 키, 비밀번호가 든 DB 주소를 막는다).
- Keep the local file private: `chmod 600 .env` (macOS/Linux).
- 키·DB 주소·클라이언트 비밀은 채팅에 붙여넣지 않는다.

## 실행
```
pip install -r requirements.txt
streamlit run src/app.py
```
모델 이름은 코드에 박지 않고 `.env`/Secrets로 바꾼다: `OPENROUTER_IMAGE_MODEL`, `OPENROUTER_FALLBACK_MODELS`,
`OPENROUTER_TEXT_MODEL`, `OPENROUTER_TEXT_FALLBACK_MODELS`. 무료 모델은 수시로 막히거나 사라진다.

## 실행 시 확인 사항
- OpenRouter API를 이용해서 실제 AI 모델이 냉장고 사진 이미지를 인식하고 레시피를 생성하게 한다.
- 매번 실행할 때마다 API가 정확하게 작동했는지, AI 모델이 문제 없이 실행되었는지를 파악하고,
  문제가 있다면 어떤 문제가 있었는지를 보고한다. 실패를 성공처럼 보이게 하거나 이전 결과를 남겨 두지 않는다.
- 앱 화면은 실패하면 "❌ …하지 못했습니다"와 시도 기록(모델별 HTTP 상태)을 그대로 보여준다.
