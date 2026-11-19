"""Every number the web UI shows must point at a file that exists in the repo."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _sources(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("src", "src_diagnoses", "src_triage", "mechanism_src", "file") and isinstance(v, str):
                out.extend(v.split(" · "))
            elif k == "plans":
                out.extend(v)
            else:
                _sources(v, out)
    elif isinstance(node, list):
        for v in node:
            _sources(v, out)


def test_every_source_link_exists():
    data = ROOT / "web" / "data"
    paths: list[str] = []
    for name in ("overview", "audit", "regression"):
        _sources(json.loads((data / f"{name}.json").read_text()), paths)
    assert paths
    missing = sorted({p for p in paths if not (ROOT / p).exists()})
    assert not missing, missing


def test_numbers_match_their_source_files():
    o = json.loads((ROOT / "web/data/overview.json").read_text())
    b = json.loads((ROOT / "results/baseline_v1.json").read_text())
    v = json.loads((ROOT / "results/eval_verify.json").read_text())
    assert o["baseline"]["pass1"]["v"] == b["pass^1"]
    assert o["verify"]["false_success"]["v"]["n"] == v["false_success"]["runs"]["n"]
