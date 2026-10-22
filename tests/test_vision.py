import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import vision  # noqa: E402
from PIL import Image  # noqa: E402


def png(size):
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


OK = json.dumps({"ingredients": [{"name": "계란"}, {"name": "우유"}]})


class ResizeTest(unittest.TestCase):
    def test_long_side_capped(self):
        out = Image.open(io.BytesIO(vision.resize_image(png((3000, 2000)))))
        self.assertEqual(max(out.size), 1024)
        self.assertEqual(out.format, "JPEG")

    def test_garbage_rejected(self):
        with self.assertRaises(vision.VisionError):
            vision.resize_image(b"not an image")


class ParseTest(unittest.TestCase):
    def test_fenced_and_deduped(self):
        text = "```json\n" + json.dumps({"ingredients": [
            {"name": " 계란 "}, {"name": "계란"}, "우유", {"x": 1}]}) + "\n```"
        self.assertEqual(vision.parse_ingredients(text), ["계란", "우유"])

    def test_empty_list_ok(self):
        self.assertEqual(vision.parse_ingredients('{"ingredients": []}'), [])

    def test_garbage_raises(self):
        for bad in ("no json", '{"ingredients": "x"}', "{broken}"):
            with self.assertRaises(ValueError):
                vision.parse_ingredients(bad)


class PostChatTest(unittest.TestCase):
    def opener(self, payload):
        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return lambda req, timeout: R(json.dumps(payload).encode())

    def test_empty_choices_is_api_error_not_keyerror(self):
        for payload in ({"choices": []}, {}, {"choices": [{"message": {"content": ""}}]}):
            with self.assertRaises(vision.ApiError):
                vision.post_chat("m", "d", "k", opener=self.opener(payload))

    def test_returns_content(self):
        p = {"choices": [{"message": {"content": "hi"}}]}
        self.assertEqual(vision.post_chat("m", "d", "k", opener=self.opener(p)), "hi")

    def test_http_error_carries_status(self):
        def boom(req, timeout):
            raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"limited"))
        with self.assertRaises(vision.ApiError) as cm:
            vision.post_chat("m", "d", "k", opener=boom)
        self.assertEqual(cm.exception.status, 429)


class RecognizeTest(unittest.TestCase):
    def run_with(self, script, models=("A", ["B", "C"])):
        calls = []
        def fake(model, url, key):
            calls.append(model)
            step = script[len(calls) - 1]
            if isinstance(step, int):
                raise vision.ApiError(step)
            return step
        sleeps = []
        return calls, sleeps, lambda: vision.recognize(
            png((50, 50)), "k", call=fake, sleep=sleeps.append, models=models)

    def test_retry_then_fallback_success(self):
        calls, sleeps, go = self.run_with([429, 429, OK])
        res = go()
        self.assertEqual(calls, ["A", "A", "B"])
        self.assertEqual(sleeps, [vision.RETRY_WAIT_SEC])
        self.assertEqual((res.model, res.ingredients), ("B", ["계란", "우유"]))

    def test_empty_200_falls_back(self):
        calls, _, go = self.run_with([200, 200, OK])
        self.assertEqual(go().model, "B")

    def test_404_skips_same_model_retry(self):
        calls, _, go = self.run_with([404, OK])
        go()
        self.assertEqual(calls, ["A", "B"])

    def test_auth_error_stops_immediately(self):
        calls, _, go = self.run_with([401])
        with self.assertRaises(vision.VisionError):
            go()
        self.assertEqual(calls, ["A"])

    def test_all_fail(self):
        _, _, go = self.run_with([429, 429, 429, 429])
        with self.assertRaises(vision.VisionError) as cm:
            go()
        self.assertEqual(len(cm.exception.attempts), 4)

    def test_bad_format_falls_back(self):
        calls, _, go = self.run_with(["not json", "still not", OK])
        self.assertEqual(go().model, "B")


class KeyTest(unittest.TestCase):
    def test_env_wins_and_secrets_fallback(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "from-env"}):
            self.assertEqual(vision.get_api_key({"OPENROUTER_API_KEY": "s"}), "from-env")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(vision.get_api_key({"OPENROUTER_API_KEY": "s"}), "s")


class SettingsTest(unittest.TestCase):
    def test_models_read_from_dotenv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("OPENROUTER_IMAGE_MODEL=a/b:free\n"
                           "OPENROUTER_FALLBACK_MODELS=c/d:free, e/f:free, a/b:free\n")
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(vision, "ENV_FILE", env):
                self.assertEqual(vision.get_models(), ("a/b:free", ["c/d:free", "e/f:free"]))

    def test_defaults_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(vision, "ENV_FILE", Path("/nonexistent/.env")):
            primary, fallbacks = vision.get_models()
            self.assertEqual(primary, vision.DEFAULT_MODEL)
            self.assertTrue(fallbacks)


if __name__ == "__main__":
    unittest.main()
