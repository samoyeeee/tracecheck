#!/usr/bin/env bash
# Publish the read-only site (web/site) as a static Hugging Face Space.
# Needs a Hugging Face write token (HF_TOKEN) and: pip install huggingface_hub
#   HF_TOKEN=... deploy/hf_static.sh <user>/<space>
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${1:?usage: deploy/hf_static.sh <user>/<space>}"
OUT="$(mktemp -d)"
cp -r web/site/. "$OUT/"
cat > "$OUT/README.md" <<'MD'
---
title: TraceCheck
emoji: 🔎
colorFrom: gray
colorTo: red
sdk: static
app_file: index.html
pinned: false
short_description: Agent failure triage on tau2-bench retail (read-only demo)
---

TraceCheck — read-only demo with pre-analysed runs. Source and the interactive version: https://github.com/samoyeeee/tracecheck
MD
python3 - "$REPO" "$OUT" <<'PY'
import os, sys
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo, folder = sys.argv[1], sys.argv[2]
api.create_repo(repo, repo_type="space", space_sdk="static", exist_ok=True)
api.upload_folder(folder_path=folder, repo_id=repo, repo_type="space", commit_message="TraceCheck read-only demo")
print(f"https://huggingface.co/spaces/{repo}")
PY
