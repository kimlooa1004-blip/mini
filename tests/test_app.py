"""Run the real app script headlessly and make sure no screen raises."""
import unittest
from pathlib import Path
from unittest import mock

import helpers
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
PAGES = Path(APP).parent / "pages"


def app(state=None):
    at = AppTest.from_file(APP, default_timeout=30)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at


class AppScreensTest(unittest.TestCase):
    def setUp(self):
        self._dir = helpers.temp_db()
        self._key = mock.patch("llm.get_api_key", return_value="dummy")
        self._key.start()

    def tearDown(self):
        self._key.stop()
        self._dir.cleanup()

    def test_first_screen_and_missing_key(self):
        at = app().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 0)
        with mock.patch("llm.get_api_key", return_value=None):
            at = app().run()
        self.assertFalse(at.exception)
        self.assertIn("OPENROUTER_API_KEY", at.error[0].value)

    def test_manual_entry_after_failed_recognition_does_not_crash(self):
        at = app({"rec_error": ("모든 모델이 응답하지 못했습니다.", ["m: HTTP 429"])}).run()
        self.assertFalse(at.exception)
        next(b for b in at.button if b.label == "재료를 직접 입력할게요").click()
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("식재료가 없습니다" in w.value for w in at.warning))

    def test_populated_list_and_clear_all_do_not_crash(self):
        import pandas as pd
        import vision
        df = pd.DataFrame({"식재료": pd.Series(["계란", "우유"], dtype="object"),
                           "수량": pd.Series([1.0, 1.0]), "단위": pd.Series(["개", "개"], dtype="object")})
        at = app({"result": vision.Recognition(["계란", "우유"], "m", ["m: 성공"]),
                  "ing_df": df, "editor_n": 1}).run()
        self.assertFalse(at.exception, at.exception)
        next(b for b in at.button if b.label == "모두 삭제").click()
        at.run()
        self.assertFalse(at.exception, at.exception)

    def test_failure_message_shown_and_half_state_does_not_crash(self):
        import vision
        # the real failure path pops result+ing_df together and keeps only rec_error ...
        at = app({"rec_error": ("실패", ["m: HTTP 500"])}).run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("식재료 인식에 실패했습니다" in e.value for e in at.error))
        self.assertFalse(any("식재료 목록 준비됨" in s.value for s in at.success))
        # ... and a result without its table must not take the page down either
        at = app({"result": vision.Recognition(["계란"], "m", [])}).run()
        self.assertFalse(at.exception, at.exception)


class PagesTest(unittest.TestCase):
    def setUp(self):
        self._dir = helpers.temp_db()

    def tearDown(self):
        self._dir.cleanup()

    def test_pages_ask_for_login_without_crashing(self):
        for page in sorted(PAGES.glob("*.py")):
            at = AppTest.from_file(str(page), default_timeout=30).run()
            self.assertFalse(at.exception, f"{page.name}: {at.exception}")
            self.assertTrue(any("로그인이 필요한 화면" in i.value for i in at.info), page.name)


if __name__ == "__main__":
    unittest.main()
