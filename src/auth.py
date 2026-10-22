"""Sign-up / log-in with bcrypt. Failure messages never reveal whether an email exists."""
import re
import time

import bcrypt

import db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores (or rejects) anything longer
MAX_NICKNAME = 20
MAX_FAILS = 5
LOCK_SECONDS = 300
BAD_LOGIN = "이메일 또는 비밀번호가 올바르지 않습니다."
# Compared against when the email is unknown, so timing doesn't leak which emails exist.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=10)).decode()
_fails = {}


class AuthError(Exception):
    pass


def normalize_email(email):
    return (email or "").strip().lower()


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def validate_signup(email, password, nickname):
    if not EMAIL_RE.match(email) or len(email) > 254:
        return "올바른 이메일 주소를 입력해 주세요."
    if len(password) < MIN_PASSWORD:
        return f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return "비밀번호가 너무 깁니다."
    if not nickname or len(nickname) > MAX_NICKNAME:
        return f"닉네임은 1~{MAX_NICKNAME}자로 입력해 주세요."
    return None


def public_user(row):
    return {"id": row["id"], "email": row["email"], "nickname": row["nickname"]}


def signup(email, password, nickname):
    email, nickname = normalize_email(email), (nickname or "").strip()
    error = validate_signup(email, password, nickname)
    if error:
        raise AuthError(error)
    try:
        user_id = db.create_user(email, hash_password(password), nickname)
    except db.DuplicateEmail as e:
        raise AuthError("이미 가입된 이메일입니다.") from e
    return {"id": user_id, "email": email, "nickname": nickname}


def login(email, password, now=time.time):
    email = normalize_email(email)
    t = now()
    recent = [x for x in _fails.get(email, []) if t - x < LOCK_SECONDS]
    if len(recent) >= MAX_FAILS:
        raise AuthError("로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.")
    row = db.get_user_by_email(email)
    ok = _check(password, row["password_hash"] if row else _DUMMY_HASH)
    if not (row and ok):
        _fails[email] = recent + [t]
        raise AuthError(BAD_LOGIN)
    _fails.pop(email, None)
    return public_user(row)
