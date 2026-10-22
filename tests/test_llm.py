import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
import llm


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener(payload):
    return lambda req, timeout: FakeResponse(json.dumps(payload).encode())


class ChatTest(unittest.TestCase):
    def test_empty_choices_is_api_error_not_keyerror(self):
        for payload in ({"choices": []}, {}, {"choices": [{"message": {"content": ""}}]}):
            with self.assertRaises(llm.ApiError):
                llm.chat("m", [], "k", opener=opener(payload))

    def test_returns_content(self):
        p = {"choices": [{"message": {"content": "hi"}}]}
        self.assertEqual(llm.chat("m", [], "k", opener=opener(p)), "hi")

    def test_http_error_carries_status(self):
        def boom(req, timeout):
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"limited"))
        with self.assertRaises(llm.ApiError) as cm:
            llm.chat("m", [], "k", opener=boom)
        self.assertEqual(cm.exception.status, 429)

    def test_base_url_override_and_key_header(self):
        seen = {}
        def grab(req, timeout):
            seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
            return FakeResponse(json.dumps({"choices": [{"message": {"content": "x"}}]}).encode())
        with mock.patch.dict("os.environ", {"OPENROUTER_BASE_URL": "http://127.0.0.1:9/v1/"}):
            llm.chat("m", [], "sekret", opener=grab)
        self.assertEqual(seen["url"], "http://127.0.0.1:9/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sekret")


class KeyFormatTest(unittest.TestCase):
    def test_stray_whitespace_and_quotes_are_stripped(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": ' "sk-or-abc"\n'}):
            self.assertEqual(llm.get_api_key(), "sk-or-abc")

    def test_unsafe_key_is_rejected_before_any_request(self):
        def never(req, timeout):
            raise AssertionError("request was sent")
        for bad in ("sk-or-a\nb", "sk-or-키", "", None):
            with self.assertRaises(llm.ApiError) as cm:
                llm.chat("m", [], bad, opener=never)
            self.assertEqual(cm.exception.status, 401)

    def test_network_failure_is_labelled_with_exception_type_only(self):
        def boom(req, timeout):
            raise urllib.error.URLError("secret-host-detail")
        with self.assertRaises(llm.ApiError) as cm:
            llm.chat("m", [], "k", opener=boom)
        self.assertEqual(llm.describe(cm.exception), "HTTP 0 (URLError)")
        self.assertNotIn("secret", llm.describe(cm.exception))

    def test_attempts_log_shows_failure_kind(self):
        def attempt(model):
            raise llm.ApiError(0, "TimeoutError")
        with self.assertRaises(llm.LLMError) as cm:
            llm.call_with_fallback("A", [], attempt, lambda s: None)
        self.assertEqual(cm.exception.attempts[0], "A: HTTP 0 (TimeoutError)")


class JsonTest(unittest.TestCase):
    def test_fenced(self):
        self.assertEqual(llm.parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_garbage(self):
        for bad in ("none", "{broken}", "[1]"):
            with self.assertRaises(ValueError):
                llm.parse_json_object(bad)


class FallbackTest(unittest.TestCase):
    def run_with(self, script, fallbacks=("B", "C")):
        calls, sleeps = [], []
        def attempt(model):
            calls.append(model)
            step = script[len(calls) - 1]
            if isinstance(step, int):
                raise llm.ApiError(step)
            if step == "bad":
                raise ValueError("bad format")
            return step
        return calls, sleeps, lambda: llm.call_with_fallback("A", list(fallbacks), attempt, sleeps.append)

    def test_third_try_on_primary_succeeds(self):
        calls, sleeps, go = self.run_with([429, 429, "ok"])
        result, model, log = go()
        self.assertEqual((result, model, calls, sleeps), ("ok", "A", ["A"] * 3, [2, 4]))
        self.assertEqual(log[-1], "A: 성공")

    def test_falls_back_after_three_429(self):
        calls, sleeps, go = self.run_with([429, 429, 429, "ok"])
        self.assertEqual(go()[1], "B")
        self.assertEqual(calls, ["A", "A", "A", "B"])
        self.assertEqual(sleeps, [2, 4])

    def test_empty_200_and_bad_format_fall_back(self):
        for script in ([200, 200, 200, "ok"], ["bad", "bad", "bad", "ok"]):
            self.assertEqual(self.run_with(script)[2]()[1], "B")

    def test_404_skips_same_model_retry(self):
        calls, _, go = self.run_with([404, "ok"])
        go()
        self.assertEqual(calls, ["A", "B"])

    def test_auth_error_stops_immediately(self):
        calls, _, go = self.run_with([401])
        with self.assertRaises(llm.LLMError):
            go()
        self.assertEqual(calls, ["A"])

    def test_all_fail_lists_every_attempt(self):
        _, _, go = self.run_with([429] * 5)
        with self.assertRaises(llm.LLMError) as cm:
            go()
        self.assertEqual(len(cm.exception.attempts), 5)


class SettingsTest(unittest.TestCase):
    def test_env_file_secrets_and_precedence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("FOO=from-file\nQUOTED='q'\n")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(llm, "ENV_FILE", env):
                self.assertEqual(llm.read_setting("FOO"), "from-file")
                self.assertEqual(llm.read_setting("QUOTED"), "q")
                self.assertEqual(llm.read_setting("FOO", {"FOO": "from-secrets"}), "from-secrets")
                self.assertIsNone(llm.read_setting("MISSING"))
            with mock.patch.dict("os.environ", {"FOO": "from-env"}), mock.patch.object(llm, "ENV_FILE", env):
                self.assertEqual(llm.read_setting("FOO", {"FOO": "s"}), "from-env")

    def test_model_list_excludes_primary(self):
        self.assertEqual(llm.parse_model_list("a, b ,,a", exclude=("a",)), ["b"])


if __name__ == "__main__":
    unittest.main()
