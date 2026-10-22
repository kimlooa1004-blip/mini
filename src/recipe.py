"""Step 2: turn a confirmed ingredient list into recipes. No Streamlit imports."""
import re
import time
from dataclasses import dataclass, field

import llm

DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_FALLBACKS = "minimax/minimax-m3.1-flash:free,google/gemma-4-31b-it:free"
MAX_ITEMS = 50
MAX_TEXT_LEN = 50
RECIPE_COUNT = 3

KINDS = ["상관없음", "한식", "양식", "중식", "일식"]
LEVELS = ["상관없음", "초급", "중급", "고급"]
TIMES = ["상관없음", "15분 이내", "30분 이내", "30분 이상"]
SERVINGS = [1, 2, 3, 4]
UNITS = ["개", "단", "병", "봉", "팩", "g", "kg", "ml", "L"]


@dataclass
class Generation:
    recipes: list
    model: str
    attempts: list = field(default_factory=list)


def get_models(secrets=None):
    primary = llm.read_setting("OPENROUTER_TEXT_MODEL", secrets) or DEFAULT_MODEL
    raw = llm.read_setting("OPENROUTER_TEXT_FALLBACK_MODELS", secrets) or DEFAULT_FALLBACKS
    return primary, llm.parse_model_list(raw, exclude=(primary,))


def clean_text(value, limit=MAX_TEXT_LEN):
    """Single line, no control characters, capped: user text goes into a prompt."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def clean_list(values, limit=MAX_ITEMS):
    out = []
    for v in values or []:
        text = clean_text(v)
        if text and text not in out:
            out.append(text)
    return out[:limit]


def ingredient_names(ingredients):
    return [clean_text(i["name"] if isinstance(i, dict) else i) for i in ingredients
            if clean_text(i["name"] if isinstance(i, dict) else i)]


def describe_ingredient(item):
    if not isinstance(item, dict):
        return clean_text(item)
    name = clean_text(item.get("name", ""))
    qty = item.get("quantity")
    if name and qty not in (None, "", 0):
        qty = f"{qty:g}" if isinstance(qty, (int, float)) else clean_text(qty, 10)
        return f"{name} {qty}{clean_text(item.get('unit', ''), 5)}"
    return name


def build_prompt(ingredients, profile=None, options=None):
    profile, options = profile or {}, options or {}
    have = ", ".join(d for d in map(describe_ingredient, ingredients) if d)
    lines = [f"보유 재료: {have}"]
    allergies = clean_list(profile.get("allergies"))
    dislikes = clean_list(profile.get("dislikes"))
    lines.append(f"알레르기(절대 사용 금지): {', '.join(allergies) or '없음'}")
    lines.append(f"기피 재료(사용하지 않기): {', '.join(dislikes) or '없음'}")
    if profile.get("diet"):
        lines.append(f"선호 식단: {clean_text(profile['diet'])}")
    for label, key in (("요리 종류", "kind"), ("난이도", "level"), ("조리 시간", "time")):
        value = options.get(key)
        if value and value != "상관없음":
            lines.append(f"{label}: {clean_text(value)}")
    if options.get("servings"):
        lines.append(f"인원: {int(options['servings'])}인분")
    lines.append(
        f"이 재료로 만들 수 있는 가정식 레시피 {RECIPE_COUNT}개를 JSON만 출력해. "
        '형식: {"recipes":[{"title":"","servings":2,"cook_time_min":15,'
        '"have":[],"missing":[],"steps":[""]}]}. '
        "have에는 보유 재료 중 쓰는 것만, missing에는 보유하지 않은 필요한 재료(양념 포함)를 넣어.")
    return "\n".join(lines)


def _as_int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _str_list(value):
    return [clean_text(v, 100) for v in value if isinstance(v, str) and clean_text(v, 100)] \
        if isinstance(value, list) else []


def _same(a, b):
    return a == b or a in b or b in a


def parse_recipes(text, ingredients, banned=()):
    """Validate a model reply into recipe dicts; ValueError if nothing usable remains."""
    names = ingredient_names(ingredients)
    banned = [b for b in clean_list(banned) if b]
    items = llm.parse_json_object(text).get("recipes")
    if not isinstance(items, list):
        raise ValueError("'recipes' is not a list")
    recipes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title", ""), 100)
        steps = _str_list(item.get("steps"))
        if not title or not steps:
            continue
        have = [h for h in _str_list(item.get("have")) if any(_same(h, n) for n in names)]
        missing = [m for m in _str_list(item.get("missing"))
                   if not any(_same(m, n) for n in names)]
        haystack = " ".join([title, *have, *missing, *steps])
        if any(b in haystack for b in banned):
            continue  # allergy / dislike filter is ours, not the model's
        recipes.append({"title": title, "servings": _as_int(item.get("servings")),
                        "cook_time_min": _as_int(item.get("cook_time_min")),
                        "have": have, "missing": missing, "steps": steps})
    if not recipes:
        raise ValueError("no usable recipes")
    return recipes[:RECIPE_COUNT]


def generate(ingredients, key, profile=None, options=None, call=llm.chat,
             sleep=time.sleep, models=None):
    """Ask the primary text model (3 tries) and fallbacks for recipes."""
    if not ingredient_names(ingredients):
        raise llm.LLMError("식재료가 없습니다. 식재료를 한 개 이상 입력해 주세요.")
    profile = profile or {}
    banned = [*clean_list(profile.get("allergies")), *clean_list(profile.get("dislikes"))]
    primary, fallbacks = models if models else get_models()
    messages = [{"role": "user", "content": build_prompt(ingredients, profile, options)}]
    recipes, model, attempts = llm.call_with_fallback(
        primary, fallbacks,
        lambda m: parse_recipes(call(m, messages, key, max_tokens=3000), ingredients, banned),
        sleep)
    return Generation(recipes, model, attempts)
