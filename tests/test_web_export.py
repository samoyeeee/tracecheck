"""Every number the web UI shows must come from, and point at, a file in the repo."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "web" / "app" / "public" / "data"


def _sources(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("src", "mechanism_src", "file", "cost_log") and isinstance(v, str):
                out.extend(v.split(" · "))
            elif k in ("plans", "sources", "files") and isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str))
            else:
                _sources(v, out)
    elif isinstance(node, list):
        for v in node:
            _sources(v, out)


def test_every_source_link_exists():
    paths: list[str] = []
    for f in [DATA / "overview.json", DATA / "regression.json", DATA / "reports" / "index.json"]:
        _sources(json.loads(f.read_text()), paths)
    assert paths
    missing = sorted({p for p in paths if not (ROOT / p).exists()})
    assert not missing, missing


def test_numbers_match_their_source_files():
    o = json.loads((DATA / "overview.json").read_text())
    b = json.loads((ROOT / "results/baseline_v1.json").read_text())
    v = json.loads((ROOT / "results/eval_verify.json").read_text())
    assert o["baseline"]["pass1"]["v"] == b["pass^1"]
    assert o["verify"]["false_success"]["v"]["n"] == v["false_success"]["runs"]["n"]
    r = json.loads((DATA / "regression.json").read_text())
    assert r["by_type_bands"]["v"] == json.loads((ROOT / "results/regression_by_type.json").read_text())


def test_page1_report_sources_exist_and_match():
    r = json.loads((DATA / "reports/bug_dropitem__task_2__trial_1.json").read_text())
    assert (ROOT / r["file"]).exists() and (ROOT / r["footer"]["cost_log"]).exists()
    stored = next(x for x in json.loads((ROOT / "results/triage/bug_dropitem.json").read_text())
                  if x["file"] == r["file"])
    assert r["tau2"]["false_success"] == stored["false_success"]
    bad = [x for x in r["comparison"] if not x["match"]]
    assert bad and all(x["field"] in {f["path"].split("[")[0] for d in stored["db_diff"] for f in d["fields"]} for x in bad)


def test_every_index_entry_has_a_report():
    for x in json.loads((DATA / "reports" / "index.json").read_text()):
        assert (DATA / "reports" / f"{x['id']}.json").exists(), x["id"]
