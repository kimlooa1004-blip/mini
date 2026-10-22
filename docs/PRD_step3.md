# PRD 3단계 — 사용자 프로필과 레시피 저장

## 1. 목표
회원가입·로그인한 사용자가 프로필을 만들고, 2단계에서 생성된 레시피를 저장·조회·삭제한다. 프로필은 2단계 레시피 생성에 반영된다.

## 2. 사용자 스토리
- 사용자로서 가입·로그인해서 내 레시피만 안전하게 보관하고 싶다.
- 사용자로서 알레르기와 기피 재료를 프로필에 저장해 추천에 반영하고 싶다.
- 사용자로서 마음에 든 레시피를 저장하고, 목록에서 보고, 지우고 싶다.

## 3. 기능 요구사항
1. 회원가입(이메일, 비밀번호, 닉네임)과 로그인·로그아웃.
2. 프로필: 닉네임, 알레르기 목록, 기피 재료 목록, 선호 식단(선택). 수정 가능.
3. 레시피 저장: 2단계 출력 스키마의 레시피 1개를 그대로 저장한다.
4. 저장 레시피 목록 조회(최신순), 상세 조회, 삭제.
5. 모든 저장·조회·삭제는 로그인한 본인의 데이터에만 허용한다.

## 4. API 연동 기술 사양
외부 AI 호출은 없고 앱 자체 API이다. (서버 → OpenRouter 호출은 1·2단계 사양을 따른다.)

| 메서드·경로 | 설명 | 인증 |
|---|---|---|
| `POST /api/auth/signup` | 가입 `{email,password,nickname}` | 불필요 |
| `POST /api/auth/login` | 로그인, 세션 쿠키 발급 | 불필요 |
| `POST /api/auth/logout` | 로그아웃 | 필요 |
| `GET /api/profile` · `PUT /api/profile` | 프로필 조회·수정 | 필요 |
| `POST /api/recipes` | 레시피 저장 (2단계 스키마) | 필요 |
| `GET /api/recipes` | 내 레시피 목록 | 필요 |
| `GET /api/recipes/{id}` | 상세 | 필요 |
| `DELETE /api/recipes/{id}` | 삭제 | 필요 |

저장 요청 예시 (2단계 출력의 레시피 1개)
```json
{"title":"대파 계란말이","servings":2,"cook_time_min":15,
 "have":["계란","대파"],"missing":["식용유"],
 "steps":["대파를 잘게 썬다","계란에 대파와 소금을 넣어 푼다","약불에서 말아 익힌다"]}
```

DB 스키마
```sql
CREATE TABLE users (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  nickname      TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE TABLE profiles (
  user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  allergies  TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
  dislikes   TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
  diet       TEXT
);
CREATE TABLE recipes (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  servings      INTEGER,
  cook_time_min INTEGER,
  have          TEXT NOT NULL,             -- JSON 배열
  missing       TEXT NOT NULL,             -- JSON 배열
  steps         TEXT NOT NULL,             -- JSON 배열
  created_at    TEXT NOT NULL
);
CREATE INDEX idx_recipes_user ON recipes(user_id, created_at DESC);
```

## 5. UI 흐름
로그인/가입 화면 → 메인(사진 업로드, 1단계) → 레시피 결과(2단계) → "저장" → 내 레시피 목록 → 상세·삭제. 헤더에서 프로필 화면으로 이동.

## 6. 비기능 요구사항
- 보안: 비밀번호는 argon2 또는 bcrypt로 해시해 저장하고 평문을 로그에 남기지 않는다. 세션 쿠키는 `HttpOnly`, `Secure`, `SameSite=Lax`. 모든 조회·삭제 쿼리는 `user_id = 로그인 사용자`로 제한한다(다른 사람 레시피 접근 시 404). SQL은 파라미터 바인딩만 사용한다. 로그인 시도는 IP·계정별로 횟수를 제한한다.
- 에러 처리: 이메일 중복, 비밀번호 규칙(8자 이상), 존재하지 않는 레시피에 각각 알맞은 상태 코드(409, 422, 404)와 문구를 반환한다.
- 개인정보: 수집 항목은 이메일, 닉네임, 알레르기·기피 재료로 최소화한다. 비밀번호·API 키는 저장소에 올리지 않는다.

## 7. 완료 조건
- 가입 → 로그인 → 레시피 저장 → 목록 조회 → 삭제가 동작한다.
- 사용자 A가 사용자 B의 레시피를 조회·삭제하려 하면 404가 된다.
- 프로필의 알레르기가 2단계 요청에 전달되어 해당 재료 레시피가 제외된다.
- DB에 평문 비밀번호가 없다.

## 8. 범위 외
소셜 로그인, 비밀번호 재설정 메일, 레시피 공유·검색, 이미지 저장.
