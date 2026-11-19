"""Local interactive TraceCheck: upload an agent run, get the analysis.

    GEMINI_API_KEY=... python -m web.serve        # then open http://127.0.0.1:8000

Serves web/ plus a small JSON API. Binds to 127.0.0.1 only: the investigator
calls a model with YOUR key, so this is not meant to be exposed publicly.
Without a key, layers 1-2 (rules + database check) still work.

  GET  /api/status                -> {"local": true, "investigator": bool, "model": ...}
  GET  /api/samples               -> run files under results/runs/ to try
  POST /api/analyze               -> body {"trajectory": {...}} or {"file": "results/runs/..."}
                                     returns {"case": ..., "token": ...}   (layers 1-2)
  POST /api/investigate           -> body {"token": ...}; returns {"case": ...} with the diagnosis
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

WEB = ROOT / "web"
UPLOADS = ROOT / "results" / "uploads"       # git-ignored: user data stays local
MAX_BODY = 8 * 1024 * 1024
SESSIONS: dict[str, dict] = {}               # token -> {"path", "case", "db_diff"}


def resolve_run_file(rel: str) -> Path:
    """Only files under results/runs/ may be read by name (no path traversal)."""
    path = (ROOT / rel).resolve()
    runs = (ROOT / "results" / "runs").resolve()
    if runs not in path.parents or path.suffix != ".json" or not path.is_file():
        raise ValueError("只能选择 results/runs/ 下的运行记录。")
    return path


def save_upload(sim: dict) -> Path:
    text = json.dumps(sim, ensure_ascii=False)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f"upload_{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    path.write_text(text)
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
            return self._json(200, {"local": True, "investigator": investigator_available(), "model": model})
        if self.path == "/api/samples":
            return self._json(200, {"samples": samples()})
        return super().do_GET()

    def do_POST(self):
        from triage.pipeline import InputError, add_diagnosis, analyze_layers

        try:
            body = self._body()
            if self.path == "/api/analyze":
                if body.get("file"):
                    path = resolve_run_file(body["file"])
                elif isinstance(body.get("trajectory"), dict):
                    path = save_upload(body["trajectory"])
                else:
                    raise ValueError("请上传或粘贴一条运行记录。")
                case, raw = analyze_layers(path)
                token = hashlib.sha256(str(path).encode()).hexdigest()[:16]
                SESSIONS[token] = {"path": path, "case": case, "db_diff": raw["db_diff"]}
                return self._json(200, {"case": case, "token": token})
            if self.path == "/api/investigate":
                if not investigator_available():
                    raise ValueError("没有设置 GEMINI_API_KEY，调查 agent 不能运行。")
                s = SESSIONS.get(body.get("token") or "")
                if not s:
                    raise ValueError("请先完成前两层分析。")
                return self._json(200, {"case": add_diagnosis(s["case"], s["path"], s["db_diff"])})
            return self._json(404, {"error": "未知接口"})
        except (InputError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:  # show the cause instead of a blank page
            traceback.print_exc()
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"TraceCheck: http://127.0.0.1:{args.port}   (investigator agent: "
          f"{'on' if investigator_available() else 'off - set GEMINI_API_KEY'})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
