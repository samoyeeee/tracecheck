"""Local server guards: only run files can be read by name; bad uploads get a clear error."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.pipeline import InputError, analyze_layers, validate_run  # noqa: E402
from web.serve import resolve_run_file  # noqa: E402


def test_only_run_files_can_be_read_by_name():
    assert resolve_run_file("results/runs/v1/task_2__trial_0.json").name == "task_2__trial_0.json"
    for bad in ("config.yaml", "../etc/passwd", "results/runs/../../config.yaml", ".env"):
        with pytest.raises(ValueError):
            resolve_run_file(bad)


def test_uploads_must_be_tau2_retail_runs():
    for bad in ({}, {"messages": []}, {"messages": [{"role": "user", "content": "hi"}]},
                {"task_id": "999", "messages": [{"role": "user", "content": "hi"}]}):
        with pytest.raises(InputError):
            validate_run(bad)


def test_live_analysis_matches_the_stored_triage():
    import json
    case, raw = analyze_layers(ROOT / "results/runs/bug_addr2/task_17__trial_0.json")
    stored = next(r for r in json.loads((ROOT / "results/triage/bug_addr2.json").read_text())
                  if r["file"].endswith("task_17__trial_0.json"))
    assert raw["false_success"] == stored["false_success"] and raw["db_diff"] == stored["db_diff"]
    assert case["timeline"][0]["step"] == 0 and case["diagnosis"] is None


def test_review_entries_are_validated(tmp_path, monkeypatch):
    import json
    import web.serve as S
    monkeypatch.setattr(S, "REVIEWS", tmp_path / "human_review.jsonl")
    S.append_review({"time": "t", "report_id": "r", "decision": "modify", "original": {}, "human": {"critical_step": 3}})
    assert json.loads(S.REVIEWS.read_text())["human"]["critical_step"] == 3
    for bad in ({"decision": "maybe"}, {"decision": "accept", "script": "x"}):
        with pytest.raises(ValueError):
            S.append_review(bad)
