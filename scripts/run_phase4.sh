#!/usr/bin/env bash
# Run every phase-4 batch from results/regression_plan.json, in order, resumable.
#   SHARDS=4 scripts/run_phase4.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=vendor/tau2-bench/.venv/bin/python
export SHARDS="${SHARDS:-4}"
for TAG in bug_auth bug_transfer bug_noconfirm bug_param v1_rerun v2; do
  ARGS=$("$PY" - "$TAG" <<'PYEOF'
import json, sys
run = json.load(open("results/regression_plan.json"))["runs"][sys.argv[1]]
args = ["--agent", run["agent"]]
if isinstance(run.get("tasks"), list):
    args += ["--task-ids", *run["tasks"]]
print(" ".join(args))
PYEOF
)
  echo "=== $TAG ($ARGS)"
  # shellcheck disable=SC2086
  scripts/run_and_push.sh "$TAG" $ARGS
done
echo "PHASE4 ALL DONE"
