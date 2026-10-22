"""Offline end-to-end run: fake OpenRouter + the real Streamlit app + a real browser.

  python tests/capture.py <output_dir>
Saves numbered PNGs of the whole user flow and exits non-zero if an expectation fails.
The "fridge photo" is a generated placeholder, not a real photo.
"""
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
API_PORT, APP_PORT = 8765, 8601
expect.set_options(timeout=60000)
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshot/run")
OUT.mkdir(parents=True, exist_ok=True)


def wait_port(port, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"port {port} never opened")


def control(fail_status=0, count=0):
    req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/__control",
                                 json.dumps({"fail_status": fail_status, "count": count}).encode())
    urllib.request.urlopen(req).read()


def fake_photo(path):
    img = Image.new("RGB", (2400, 1600), (235, 240, 245))
    d = ImageDraw.Draw(img)
    for i, color in enumerate([(240, 180, 60), (250, 250, 250), (60, 160, 80), (240, 120, 40), (130, 200, 90)]):
        d.rectangle([200 + i * 420, 300, 520 + i * 420, 1300], fill=color, outline=(80, 80, 80), width=6)
    img.save(path, "JPEG", quality=95)


def main():
    tmp = tempfile.mkdtemp()
    photo = Path(tmp) / "fridge.jpg"
    fake_photo(photo)
    env = {**os.environ, "OPENROUTER_API_KEY": "test-key", "APP_DB_PATH": f"{tmp}/t.db",
           "OPENROUTER_BASE_URL": f"http://127.0.0.1:{API_PORT}/v1"}
    api = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_openrouter.py"), str(API_PORT)])
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "src/app.py"),
                            "--server.headless", "true", "--server.port", str(APP_PORT),
                            "--browser.gatherUsageStats", "false"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_port(API_PORT)
        wait_port(APP_PORT)
        chrome = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")[0]
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            page.set_default_timeout(60000)
            n = [0]

            def shot(name, full=True):
                n[0] += 1
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{n[0]:02d}_{name}.png"), full_page=full)

            def go(text):
                page.get_by_role("link", name=text).first.click()
                page.wait_for_timeout(1500)

            page.goto(f"http://localhost:{APP_PORT}")
            expect(page.get_by_role("heading", name="🥬 냉장고 레시피 추천")).to_be_visible()
            shot("초기화면")

            # --- sign up (sidebar) ---
            page.get_by_role("tab", name="회원가입").click()
            page.locator('input[aria-label="이메일"]:visible').fill("kim@example.com")
            page.locator('input[aria-label="닉네임"]').fill("김냉장")
            page.locator('input[aria-label^="비밀번호"]:visible').fill("password123")
            page.get_by_role("button", name="회원가입").click()
            expect(page.get_by_text("김냉장")).to_be_visible()
            shot("회원가입후_로그인상태")

            # --- step 1: upload + recognise, with two 429s in a row (retry path) ---
            page.set_input_files('input[type="file"]', str(photo))
            expect(page.get_by_text("식재료 인식하기")).to_be_visible()
            shot("사진업로드")
            control(429, 2)
            page.get_by_role("button", name="식재료 인식하기").click()
            expect(page.get_by_text("식재료 목록 준비됨")).to_be_visible()
            expect(page.get_by_text("이미지 축소:")).to_be_visible()
            page.get_by_text("시도 기록").first.click()
            shot("인식결과_429재시도후성공")

            # --- step 2: options + recipes ---
            page.get_by_role("button", name="레시피 추천받기").click()
            expect(page.get_by_text("레시피 3개")).to_be_visible()
            page.get_by_text("자세히 보기").first.click()
            shot("레시피추천")

            # --- step 3: save, list, delete ---
            page.get_by_role("button", name="레시피 저장").first.click()
            expect(page.get_by_text("저장했습니다")).to_be_visible()
            shot("레시피저장완료")
            go("내 레시피")
            expect(page.get_by_text("계란우유 볶음")).to_be_visible()
            shot("내레시피목록")

            # --- profile + allergy-aware regeneration ---
            go("프로필")
            page.locator('input[aria-label="닉네임"]').fill("김냉장2")
            page.locator('input[aria-label^="알레르기"]').fill("당근")
            page.get_by_role("button", name="저장").click()
            expect(page.get_by_text("프로필을 저장했습니다")).to_be_visible()
            shot("프로필저장")

            # --- failure is reported honestly, previous result is not left on screen ---
            go("app")
            page.wait_for_timeout(1500)
            expect(page.get_by_text("식재료 목록 준비됨")).to_be_visible()
            page.wait_for_timeout(5200)  # past the 5s cool-down
            control(500, 99)
            page.get_by_role("button", name="다시 추천받기").click()
            expect(page.get_by_text("레시피를 만들지 못했습니다")).to_be_visible(timeout=120000)
            assert page.get_by_text("레시피 3개").count() == 0, "stale recipes still shown"
            shot("AI실패시_정직한보고")
            control(0, 0)

            # --- delete from my recipes ---
            go("내 레시피")
            page.get_by_role("button", name="삭제").first.click()
            expect(page.get_by_text("저장된 레시피가 없습니다")).to_be_visible()
            shot("레시피삭제후")

            # --- logout hides account-bound pages ---
            page.get_by_role("button", name="로그아웃").click()
            expect(page.get_by_text("로그인이 필요한 화면입니다")).to_be_visible()
            shot("로그아웃후_로그인필요")

            # --- log back in: wrong password is refused with a generic message, right one works ---
            page.locator('input[aria-label="이메일"]:visible').fill("kim@example.com")
            page.locator('input[aria-label^="비밀번호"]:visible').fill("wrong-password")
            page.get_by_role("button", name="로그인", exact=True).click()
            expect(page.get_by_text("이메일 또는 비밀번호가 올바르지 않습니다")).to_be_visible()
            shot("로그인실패_일반적인안내문")
            page.locator('input[aria-label="이메일"]:visible').fill("kim@example.com")
            page.locator('input[aria-label^="비밀번호"]:visible').fill("password123")
            page.get_by_role("button", name="로그인", exact=True).click()
            expect(page.get_by_text("김냉장2")).to_be_visible()
            go("프로필")
            expect(page.locator('input[aria-label="닉네임"]')).to_have_value("김냉장2")
            expect(page.locator('input[aria-label^="알레르기"]')).to_have_value("당근")

            # --- recognition fails everywhere: honest error + manual-entry escape hatch ---
            go("app")
            page.set_input_files('input[type="file"]', str(photo))
            control(500, 99)
            page.get_by_role("button", name="식재료 인식하기").click()
            expect(page.get_by_text("식재료 인식에 실패했습니다")).to_be_visible(timeout=120000)
            shot("인식실패_정직한보고")
            control(0, 0)
            page.get_by_role("button", name="재료를 직접 입력할게요").click()
            expect(page.get_by_text("식재료가 없습니다. 아래 표에서 직접 추가할 수 있어요.")).to_be_visible()
            shot("직접입력_빈목록")
            browser.close()
        calls = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/").read())["calls"]
        print("model calls seen by the fake API:", calls)
        print("OK — screenshots in", OUT)
    finally:
        app.terminate()
        api.terminate()


if __name__ == "__main__":
    main()
