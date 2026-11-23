"""Local interactive TraceCheck: import an agent run, get the diagnosis report.

    cd web/app && npm install && npm run build      # once: builds web/site
    GEMINI_API_KEY=... ZHIPU_API_KEY=... python -m web.serve   # then open http://127.0.0.1:8000

Serves web/site plus a small JSON API. Binds to 127.0.0.1 only: the investigator
and the translator call models with YOUR keys, so this is not for public use.
Without the investigator key, layers 1-2 (rules + database check) still work.

  GET  /api/status   -> {"local": true, "investigator": bool, "model": ...}
  GET  /api/samples  -> run files under results/runs/ to try
  POST /api/report   -> body {"file": "results/..."} or {"trajectory": {...}}, plus "ai", "zh" flags;
                        returns the page-1 report (triage.pipeline.build_report)
  POST /api/review   -> appends one human review (accept / reject / modify) to results/human_review.jsonl

Public mode (PUBLIC_MODE=1, used on Hugging Face Spaces, see deploy/):
  binds 0.0.0.0:$PORT, caps model use per visitor and per day (web/limits.py),
  runs one AI analysis at a time, keeps reviews in the visitor's browser only,
  and offers no server-side samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WEB = ROOT / "web" / "site"
REVIEWS = ROOT / "results" / "human_review.jsonl"
UPLOADS = ROOT / "results" / "uploads"       # git-ignored: user data stays local
PUBLIC = os.environ.get("PUBLIC_MODE") == "1"
MAX_BODY = (2 if PUBLIC else 8) * 1024 * 1024
MAX_UPLOADS = 300                            # public mode: keep only the newest uploads on disk
_limits = None


def limits():
    global _limits
    if _limits is None:
        from web.limits import Limits
        _limits = Limits(ROOT / "results" / ".public_usage.json")
    return _limits
REVIEW_KEYS = {"time", "report_id", "file", "original", "decision", "human", "note"}


def resolve_run_file(rel: str) -> Path:
    """Only run files under results/runs/ or results/uploads/ may be read by name (no path traversal)."""
    path = (ROOT / rel).resolve()
    allowed = [(ROOT / "results" / d).resolve() for d in ("runs", "uploads")]
    if not any(a in path.parents for a in allowed) or path.suffix != ".json" or not path.is_file():
        raise ValueError("只能选择 results/runs/ 下的运行记录。")
    return path


def append_review(entry: dict) -> None:
    if set(entry) - REVIEW_KEYS or entry.get("decision") not in ("accept", "reject", "modify"):
        raise ValueError("复核记录格式不对。")
    REVIEWS.parent.mkdir(parents=True, exist_ok=True)
    with REVIEWS.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save_upload(sim: dict) -> Path:
    text = json.dumps(sim, ensure_ascii=False)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f"upload_{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    path.write_text(text)
    if PUBLIC:
        old = sorted(UPLOADS.glob("upload_*.json"), key=lambda p: p.stat().st_mtime)[:-MAX_UPLOADS]
        for p in old:
            p.unlink(missing_ok=True)
    return path


def investigator_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def samples() -> list[dict]:
    """A few runs per batch to try, failures first."""
    out = []
    for tag in ("v1", "bug_addr2", "bug_dropitem", "v2"):
        path = ROOT / "results" / "triage" / f"{tag}.json"
        if not path.exists():
            continue
        reports = sorted(json.loads(path.read_text()), key=lambda r: (r["tau2_success"], int(r["task_id"]), r["trial"]))
        for r in reports[:25]:
            out.append({"file": r["file"], "tag": tag, "task_id": r["task_id"], "trial": r["trial"],
                        "success": r["tau2_success"], "false_success": r["false_success"]})
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("文件太大（上限 8 MB）。")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"不是合法的 JSON：{exc}")

    def do_GET(self):
        if self.path == "/api/status":
            import yaml
            model = yaml.safe_load((ROOT / "config.yaml").read_text())["models"]["investigator"]
            st = {"local": True, "public": PUBLIC, "investigator": investigator_available(), "model": model,
                  "reviews": "browser" if PUBLIC else "server"}
            if PUBLIC:
                st["remaining"] = limits().remaining(self._ip())
            return self._json(200, st)
        if self.path == "/api/samples":
            return self._json(200, {"samples": [] if PUBLIC else samples()})
        if self.path == "/api/reviews" and PUBLIC:
            return self._json(200, {"reviews": {}, "file": None})
        if self.path == "/api/reviews":   # latest human decision per report
            last = {}
            if REVIEWS.exists():
                for line in REVIEWS.read_text().splitlines():
                    if line.strip():
                        e = json.loads(line)
                        last[e.get("report_id")] = e
            return self._json(200, {"reviews": last, "file": str(REVIEWS.relative_to(ROOT))})
        return super().do_GET()

    def do_POST(self):
        from triage.pipeline import InputError, build_report
        from web.limits import LimitExceeded

        try:
            body = self._body()
            if self.path == "/api/report":
                if body.get("file"):
                    path = resolve_run_file(body["file"])
                    if PUBLIC and UPLOADS.resolve() not in path.parents:
                        raise ValueError("在线版只能分析你上传的记录。")
                elif isinstance(body.get("trajectory"), dict):
                    from triage.pipeline import validate_run
                    validate_run(body["trajectory"])
                    path = save_upload(body["trajectory"])
                else:
                    raise ValueError("请上传或粘贴一条运行记录。")
                ai = bool(body.get("ai")) and investigator_available()
                zh = bool(body.get("zh"))
                if not PUBLIC:
                    return self._json(200, build_report(path, ai=ai, zh=zh))
                if not (ai or zh):
                    limits().take_check(self._ip())
                    return self._json(200, build_report(path))
                if not limits().ai_running.acquire(blocking=False):
                    raise LimitExceeded("现在有别人在用调查 agent，请过一分钟再试。")
                try:
                    limits().take_ai(self._ip())
                    return self._json(200, build_report(path, ai=ai, zh=zh))
                finally:
                    limits().ai_running.release()
            if self.path == "/api/review":
                if PUBLIC:
                    return self._json(403, {"error": "在线版的复核只保存在你的浏览器里。"})
                append_review(body)
                return self._json(200, {"saved": str(REVIEWS.relative_to(ROOT))})
            return self._json(404, {"error": "未知接口"})
        except LimitExceeded as exc:
            return self._json(429, {"error": str(exc)})
        except (InputError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:  # show the cause instead of a blank page
            traceback.print_exc()
            msg = "服务器出错了，请稍后再试。" if PUBLIC else f"{type(exc).__name__}: {exc}"
            return self._json(500, {"error": msg})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = ap.parse_args(argv)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    if not (WEB / "index.html").exists():
        sys.exit("web/site is missing: run `cd web/app && npm install && npm run build` first.")
    host = "0.0.0.0" if PUBLIC else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), Handler)
    print(f"TraceCheck{' (public mode)' if PUBLIC else ''}: http://{host}:{args.port}   (investigator agent: "
          f"{'on' if investigator_available() else 'off - set GEMINI_API_KEY'})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
