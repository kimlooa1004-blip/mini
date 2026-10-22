"""Shared OpenRouter plumbing: settings, one chat call, retry with backoff, fallback."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Seconds to wait before the 2nd and 3rd attempt on the same model.
RETRY_WAITS = (2, 4)
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class LLMError(Exception):
    """Failure with a message that is safe to show to the user."""

    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


class ApiError(Exception):
    def __init__(self, status, message=""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.detail = message


def describe(e):
    """Short label for the attempts log. Network-level failures (status 0) carry the exception type."""
    if e.status in (0, 200) and e.detail:
        return f"HTTP {e.status} ({e.detail})"
    return f"HTTP {e.status}"


def read_setting(name, secrets=None):
    """Env var first, then a secrets mapping (Streamlit Cloud), then repo .env."""
    value = os.environ.get(name)
    if not value and secrets is not None:
        try:
            value = secrets.get(name)
        except Exception:
            value = None
    if not value and ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            key, _, raw = line.partition("=")
            if key.strip() == name:
                value = raw.strip().strip("\"'")
    return value or None


def get_api_key(secrets=None):
    key = read_setting("OPENROUTER_API_KEY", secrets)
    return key.strip().strip("\"'").strip() if key else None


def key_is_header_safe(key):
    """HTTP headers only take printable ASCII; a stray newline or Korean character breaks the call."""
    return bool(key) and key.isascii() and key.isprintable()


def parse_model_list(raw, exclude=()):
    return [m.strip() for m in (raw or "").split(",")
            if m.strip() and m.strip() not in exclude]


def chat(model, messages, key, max_tokens=1500, timeout=120, opener=urllib.request.urlopen):
    """Call the model once and return the reply text. Raises ApiError on any failure."""
    if not key_is_header_safe(key):
        raise ApiError(401, "API 키에 공백·줄바꿈·한글 등 사용할 수 없는 문자가 있습니다")
    base = (read_setting("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    body = json.dumps({"model": model, "max_tokens": max_tokens, "messages": messages}).encode()
    req = urllib.request.Request(base + "/chat/completions", body, {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with opener(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace")[:200]) from e
    except Exception as e:  # network, timeout, bad JSON
        raise ApiError(0, type(e).__name__) from e
    # Some providers answer 200 with no choices; never index blindly.
    choices = data.get("choices") if isinstance(data, dict) else None
    message = choices[0].get("message") if choices else None
    content = (message or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(200, "empty response")
    return content


def parse_json_object(text):
    """Cut the first '{' .. last '}' out of a reply and parse it; ValueError if unusable."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON root is not an object")
    return data


def call_with_fallback(primary, fallbacks, attempt, sleep=time.sleep):
    """Run attempt(model) on the primary up to 3 times (2s, 4s waits), then once per fallback.

    attempt returns a result or raises ApiError / ValueError. Returns
    (result, model_used, attempts_log). Raises LLMError when everything fails;
    401/403 stop immediately because no other model can fix a bad key.
    """
    order = [(primary, i) for i in range(len(RETRY_WAITS) + 1)] + [(m, 0) for m in fallbacks]
    attempts, dead = [], set()
    for model, nth in order:
        if model in dead:
            continue
        if nth > 0:
            sleep(RETRY_WAITS[nth - 1])
        try:
            result = attempt(model)
        except ApiError as e:
            attempts.append(f"{model}: {describe(e)}")
            if e.status in (401, 403):
                raise LLMError(
                    "API 키가 거부되었습니다. .env의 키와 OpenRouter 키 상태를 확인해 주세요.",
                    attempts) from e
            if e.status not in (0, 200, 429) and e.status < 500:
                dead.add(model)  # 404 etc.: retrying the same model won't help
            continue
        except ValueError:
            attempts.append(f"{model}: 응답 형식 오류")
            continue
        attempts.append(f"{model}: 성공")
        return result, model, attempts
    raise LLMError("모든 모델이 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.", attempts)
