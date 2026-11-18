#!/usr/bin/env bash
# Run the phase-4b batches from results/regression_plan_4b.json, resumable.
#   SHARDS=4 scripts/run_phase4b.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=vendor/tau2-bench/.venv/bin/python
export SHARDS="${SHARDS:-4}"
for TAG in bug_addr2 bug_dropitem; do
  ARGS=$("$PY" - "$TAG" <<'PYEOF'
import json, sys
run = json.load(open("results/regression_plan_4b.json"))["runs"][sys.argv[1]]
print(" ".join(["--agent", run["agent"], "--task-ids", *run["tasks"]]))
PYEOF
)
  echo "=== $TAG ($ARGS)"
  # shellcheck disable=SC2086
  scripts/run_and_push.sh "$TAG" $ARGS
done
echo "PHASE4B ALL DONE"
