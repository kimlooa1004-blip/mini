import io
import json
import unittest
from pathlib import Path
from unittest import mock

import helpers
import llm
import vision
from PIL import Image

OK = json.dumps({"ingredients": [{"name": "계란"}, {"name": "우유"}]})


class ResizeTest(unittest.TestCase):
    def test_long_side_capped(self):
        out = Image.open(io.BytesIO(vision.resize_image(helpers.png((3000, 2000)))))
        self.assertEqual(max(out.size), 1024)
        self.assertEqual(out.format, "JPEG")

    def test_garbage_rejected(self):
        with self.assertRaises(llm.LLMError):
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


class RecognizeTest(unittest.TestCase):
    def test_sends_image_and_returns_names(self):
        seen = {}
        def fake(model, messages, key, max_tokens):
            seen.update(model=model, key=key, content=messages[0]["content"])
            return OK
        res = vision.recognize(helpers.png(), "k", call=fake, sleep=lambda s: None,
                               models=("A", ["B"]))
        self.assertEqual((res.model, res.ingredients), ("A", ["계란", "우유"]))
        self.assertEqual(seen["key"], "k")
        self.assertTrue(seen["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_fallback_model_used_after_429s(self):
        calls = []
        def fake(model, messages, key, max_tokens):
            calls.append(model)
            if model == "A":
                raise llm.ApiError(429)
            return OK
        res = vision.recognize(helpers.png(), "k", call=fake, sleep=lambda s: None,
                               models=("A", ["B"]))
        self.assertEqual((res.model, calls), ("B", ["A", "A", "A", "B"]))


class ModelSettingsTest(unittest.TestCase):
    def test_models_read_from_dotenv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("OPENROUTER_IMAGE_MODEL=a/b:free\n"
                           "OPENROUTER_FALLBACK_MODELS=c/d:free, e/f:free, a/b:free\n")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(llm, "ENV_FILE", env):
                self.assertEqual(vision.get_models(), ("a/b:free", ["c/d:free", "e/f:free"]))

    def test_defaults_when_unset(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(llm, "ENV_FILE", Path("/nonexistent/.env")):
            primary, fallbacks = vision.get_models()
            self.assertEqual(primary, vision.DEFAULT_MODEL)
            self.assertTrue(fallbacks)


if __name__ == "__main__":
    unittest.main()
