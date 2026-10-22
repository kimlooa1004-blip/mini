"""Tiny stand-in for OpenRouter's /chat/completions, for offline end-to-end runs.

  python tests/fake_openrouter.py [port]      (default 8765)
Needs "Authorization: Bearer test-key". Control it with POST /__control
  {"fail_status": 429, "count": 3}   -> the next 3 chat calls fail with that status.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = {"fail_status": 0, "count": 0, "calls": []}
FRIDGE = ["계란", "우유", "대파", "당근", "양상추"]


def recipes_for(prompt):
    line = next((l for l in prompt.splitlines() if l.startswith("보유 재료:")), "")
    names = [m.group(0).strip() for part in line.split(":", 1)[-1].split(",")
             if (m := re.match(r"[^\d]+", part.strip()))] or ["계란"]
    a, b = names[0], names[1] if len(names) > 1 else names[0]
    return {"recipes": [
        {"title": f"{a}{b} 볶음", "servings": 2, "cook_time_min": 15, "have": [a, b],
         "missing": ["소금", "식용유"], "steps": [f"{a}와 {b}를 손질한다", "팬에 기름을 두르고 볶는다", "소금으로 간한다"]},
        {"title": f"{a}찜", "servings": 2, "cook_time_min": 20, "have": [a],
         "missing": [], "steps": [f"{a}를 풀어 그릇에 담는다", "중불에서 10분 찐다"]},
        {"title": f"{b} 국", "servings": 3, "cook_time_min": 25, "have": [b],
         "missing": ["멸치 육수"], "steps": ["육수를 끓인다", f"{b}를 넣고 5분 더 끓인다"]}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/__control":
            STATE.update(fail_status=body.get("fail_status", 0), count=body.get("count", 0))
            return self._send(200, {"ok": True})
        if self.headers.get("Authorization") != "Bearer test-key":
            return self._send(401, {"error": {"message": "bad key", "code": 401}})
        content = body["messages"][0]["content"]
        STATE["calls"].append(body["model"])
        if STATE["count"] > 0:
            STATE["count"] -= 1
            return self._send(STATE["fail_status"], {"error": {"message": "simulated", "code": STATE["fail_status"]}})
        if isinstance(content, list):  # image request
            text = json.dumps({"ingredients": [{"name": n} for n in FRIDGE]}, ensure_ascii=False)
        else:
            text = json.dumps(recipes_for(content), ensure_ascii=False)
        self._send(200, {"choices": [{"message": {"content": text}}]})

    def do_GET(self):
        self._send(200, {"calls": STATE["calls"]})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), Handler).serve_forever()
