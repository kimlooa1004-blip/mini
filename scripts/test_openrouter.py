"""Smoke-test OpenRouter text and image models. Stdlib only.

Usage (from the repo root, where .env lives):  python scripts/test_openrouter.py
The API key is read from .env / OPENROUTER_API_KEY and is never printed.
"""
import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"
TEXT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
IMAGE_MODEL = "google/gemma-4-26b-a4b-it:free"


def load_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    env = Path(".env")
    if not key and env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "OPENROUTER_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        sys.exit("OPENROUTER_API_KEY not found (.env missing or misnamed?)")
    return key


def red_square_png(size=64):
    """Build a solid red PNG with the stdlib so no image file is needed."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    row = b"\x00" + b"\xff\x00\x00" * size
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def ask(key, model, content):
    body = json.dumps({"model": model, "max_tokens": 200,
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(URL, body, {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    msg = (data.get("choices") or [{}])[0].get("message", {})
    text = (msg.get("content") or "").strip()
    return bool(text), text or json.dumps(data)[:300]


def main():
    key = load_key()
    png = base64.b64encode(red_square_png()).decode()
    tests = [
        ("TEXT ", TEXT_MODEL, "Reply with exactly one short sentence: what is 2+3?", "5"),
        ("IMAGE", IMAGE_MODEL, [
            {"type": "text", "text": "What single color is this image? Answer in one word."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        ], "red"),
    ]
    failed = 0
    for label, model, content, expect in tests:
        ok, text = ask(key, model, content)
        hit = ok and expect in text.lower()
        failed += not hit
        print(f"[{label}] {model}\n  {'PASS' if hit else 'FAIL'} - {text[:200]!r}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
