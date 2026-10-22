"""Fridge-photo ingredient recognition via OpenRouter. No Streamlit imports."""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"
# Other providers than the primary, so one provider's rate limit doesn't sink all.
DEFAULT_FALLBACKS = "minimax/minimax-m3.1-flash:free,google/gemma-4-31b-it:free"
MAX_SIDE = 1024
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
RETRY_WAIT_SEC = 2
MAX_INGREDIENTS = 50
MAX_NAME_LEN = 50

PROMPT = (
    "이 냉장고 사진에 보이는 식재료를 한국어 일반명으로 찾아 JSON만 출력해. "
    '형식: {"ingredients":[{"name":"..."}]}. 식재료가 없으면 빈 배열.'
)


class VisionError(Exception):
    """Failure with a message that is safe to show to the user."""

    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


class ApiError(Exception):
    def __init__(self, status, message=""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


@dataclass
class Recognition:
    ingredients: list
    model: str
    attempts: list = field(default_factory=list)


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


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
    return read_setting("OPENROUTER_API_KEY", secrets)


def get_models(secrets=None):
    primary = read_setting("OPENROUTER_IMAGE_MODEL", secrets) or DEFAULT_MODEL
    raw = read_setting("OPENROUTER_FALLBACK_MODELS", secrets) or DEFAULT_FALLBACKS
    fallbacks = [m.strip() for m in raw.split(",") if m.strip() and m.strip() != primary]
    return primary, fallbacks


def resize_image(data, max_side=MAX_SIDE):
    """Shrink so the long side is <= max_side and re-encode as JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise VisionError("이미지를 읽을 수 없습니다. JPG/PNG/WebP 사진인지 확인해 주세요.") from e
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def to_data_url(jpeg):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def parse_ingredients(text):
    """Pull the ingredient names out of a model reply; raises ValueError if unusable."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start:end + 1])
    items = data.get("ingredients")
    if not isinstance(items, list):
        raise ValueError("'ingredients' is not a list")
    names, seen = [], set()
    for item in items:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str):
            continue
        name = name.strip()[:MAX_NAME_LEN]
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names[:MAX_INGREDIENTS]


def post_chat(model, data_url, key, timeout=120, opener=urllib.request.urlopen):
    """Call the model once and return the reply text. Raises ApiError on any failure."""
    body = json.dumps({
        "model": model,
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }).encode()
    req = urllib.request.Request(API_URL, body, {
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


def recognize(image_bytes, key, call=post_chat, sleep=time.sleep, models=None):
    """Resize, then try primary (twice) and fallbacks until one returns ingredients."""
    primary, fallbacks = models if models else get_models()
    data_url = to_data_url(resize_image(image_bytes))
    order = [primary, primary] + fallbacks
    attempts, dead, prev = [], set(), None
    for model in order:
        if model in dead:
            continue
        if model == prev:
            sleep(RETRY_WAIT_SEC)
        prev = model
        try:
            names = parse_ingredients(call(model, data_url, key))
        except ApiError as e:
            attempts.append(f"{model}: HTTP {e.status}")
            if e.status in (401, 403):
                raise VisionError(
                    "API 키가 거부되었습니다. .env의 키와 OpenRouter 키 상태를 확인해 주세요.",
                    attempts) from e
            if e.status not in (0, 200, 429) and e.status < 500:
                dead.add(model)  # 404 etc.: retrying the same model won't help
            continue
        except ValueError:
            attempts.append(f"{model}: 응답 형식 오류")
            continue
        attempts.append(f"{model}: 성공")
        return Recognition(names, model, attempts)
    raise VisionError("모든 모델이 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.", attempts)
