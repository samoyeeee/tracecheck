"""Regression cases: creation and the failure paths of a replay (no model calls)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import triage.regression_case as RC  # noqa: E402

SRC = "results/runs/bug_dropitem/task_2__trial_1.json"


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(RC, "CASES", tmp_path / "cases")
    monkeypatch.setattr(RC, "REPLAYS", tmp_path / "replays")


def test_case_keeps_task_initial_state_expectation_and_evidence(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    c = RC.create_case(SRC)
    assert c["task_id"] == "2" and c["source_version"] == "bug_dropitem"
    assert c["initial_db_hash"] == RC._initial_hash("2")            # reset is reproducible
    assert any(e["field"] == "return_items" for e in c["expected"])
    assert c["failure"]["rows"] and c["replays"] == []
    assert RC.create_case(SRC)["created"] == c["created"]          # idempotent


def test_replay_failures_are_recorded_not_counted_as_passes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    c = RC.create_case(SRC)
    rec = RC.replay(c["id"], "no_such_version")
    assert rec["status"] == "error" and rec["error_kind"] == "bad_version"
    # a changed initial database must stop the replay before any model call
    case = json.loads((RC.CASES / f"{c['id']}.json").read_text())
    case["initial_db_hash"] = "different"
    (RC.CASES / f"{c['id']}.json").write_text(json.dumps(case))
    rec = RC.replay(c["id"], "v1")
    assert rec["error_kind"] == "reset_failed" and rec["model_calls"] == 0
    s = RC.summarise(RC.load_case(c["id"]))
    assert s["v1"]["passed"] == 0 and s["v1"]["errors"] == 1 and "还没有" in s["v1"]["statement"]
