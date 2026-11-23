"""Usage limits for the public (Hugging Face Spaces) deployment.

The public server spends the owner's free-tier model quota, so every visitor
is capped. Counters reset at 00:00 UTC and are kept in a small JSON file so a
restart does not reset them. Settings come from environment variables:

  AI_DAILY_LIMIT        AI analyses per day, all visitors together   (default 40)
  AI_PER_IP_DAILY       AI analyses per day, per visitor IP           (default 3)
  CHECKS_PER_IP_DAILY   rules + database checks per day, per IP       (default 30)

One AI analysis = 3 investigator calls + a few translation calls. Only one AI
analysis runs at a time; a second one gets "busy" instead of queueing.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


class LimitExceeded(Exception):
    """Shown to the visitor as is (Chinese)."""


class Limits:
    def __init__(self, path: Path, ai_daily: int | None = None, ai_per_ip: int | None = None,
                 checks_per_ip: int | None = None, today=None):
        self.path = path
        self.ai_daily = _env_int("AI_DAILY_LIMIT", 40) if ai_daily is None else ai_daily
        self.ai_per_ip = _env_int("AI_PER_IP_DAILY", 3) if ai_per_ip is None else ai_per_ip
        self.checks_per_ip = _env_int("CHECKS_PER_IP_DAILY", 30) if checks_per_ip is None else checks_per_ip
        self._today = today or (lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self._lock = threading.Lock()
        self.ai_running = threading.Semaphore(1)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        if data.get("day") != self._today():
            data = {"day": self._today(), "ai_total": 0, "ai": {}, "checks": {}}
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def remaining(self, ip: str) -> dict:
        with self._lock:
            d = self._load()
            return {"ai_today": max(0, self.ai_daily - d["ai_total"]),
                    "ai_you": max(0, self.ai_per_ip - d["ai"].get(ip, 0)),
                    "checks_you": max(0, self.checks_per_ip - d["checks"].get(ip, 0))}

    def take_check(self, ip: str) -> None:
        with self._lock:
            d = self._load()
            if d["checks"].get(ip, 0) >= self.checks_per_ip:
                raise LimitExceeded(f"今天的分析次数已用完（每人每天 {self.checks_per_ip} 次），明天再来。")
            d["checks"][ip] = d["checks"].get(ip, 0) + 1
            self._save(d)

    def take_ai(self, ip: str) -> None:
        with self._lock:
            d = self._load()
            if d["ai_total"] >= self.ai_daily:
                raise LimitExceeded("今天的调查 agent 总额度已用完，规则检查和数据库核验仍可用，明天再来试 AI 诊断。")
            if d["ai"].get(ip, 0) >= self.ai_per_ip:
                raise LimitExceeded(f"你今天的 AI 诊断次数已用完（每人每天 {self.ai_per_ip} 次），规则检查和数据库核验仍可用。")
            d["ai_total"] += 1
            d["ai"][ip] = d["ai"].get(ip, 0) + 1
            self._save(d)
