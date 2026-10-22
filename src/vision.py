"""Fridge-photo ingredient recognition. No Streamlit imports."""
import base64
import io
import time
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

import llm
from llm import ApiError, LLMError

VisionError = LLMError  # kept for callers written before llm.py existed

DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"
# Other providers than the primary, so one provider's rate limit doesn't sink all.
DEFAULT_FALLBACKS = "minimax/minimax-m3.1-flash:free,google/gemma-4-31b-it:free"
MAX_SIDE = 1536  # small items on fridge shelves blur away at 1024
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_INGREDIENTS = 50
MAX_NAME_LEN = 50

PROMPT = (
    "너는 냉장고 사진을 보고 식재료를 빠짐없이 찾아내는 도우미야. "
    "사진을 선반(칸)별로, 왼쪽에서 오른쪽으로 하나씩 훑어보고, 눈에 보이는 식재료를 모두 찾아. "
    "채소, 과일, 계란, 유제품(우유·치즈·요거트), 고기·생선, 소스·병조림, 음료까지 포함해. "
    "같은 재료가 여러 개여도 이름은 한 번만 적고, 한국어 일반명으로 써. "
    "그릇·용기·냉장고 부품은 제외하고, 사진에 실제로 보이지 않는 재료는 지어내지 마. "
    "형식은 JSON만: "
    '{"ingredients":[{"name":"..."}]}. 식재료가 전혀 없으면 빈 배열.'
)


@dataclass
class Recognition:
    ingredients: list
    model: str
    attempts: list = field(default_factory=list)


def get_api_key(secrets=None):
    return llm.get_api_key(secrets)


def get_models(secrets=None):
    primary = llm.read_setting("OPENROUTER_IMAGE_MODEL", secrets) or DEFAULT_MODEL
    raw = llm.read_setting("OPENROUTER_FALLBACK_MODELS", secrets) or DEFAULT_FALLBACKS
    return primary, llm.parse_model_list(raw, exclude=(primary,))


def resize_image(data, max_side=MAX_SIDE):
    """Shrink so the long side is <= max_side and re-encode as JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise LLMError("이미지를 읽을 수 없습니다. JPG/PNG/WebP 사진인지 확인해 주세요.") from e
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def to_data_url(jpeg):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def parse_ingredients(text):
    """Pull the ingredient names out of a model reply; raises ValueError if unusable."""
    items = llm.parse_json_object(text).get("ingredients")
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


def recognize(image_bytes, key, call=llm.chat, sleep=time.sleep, models=None):
    """Resize, then ask the primary model (3 tries) and fallbacks for the ingredient list."""
    primary, fallbacks = models if models else get_models()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": to_data_url(resize_image(image_bytes))}},
    ]}]
    names, model, attempts = llm.call_with_fallback(
        primary, fallbacks,
        lambda m: parse_ingredients(call(m, messages, key, max_tokens=1500)), sleep)
    return Recognition(names, model, attempts)
