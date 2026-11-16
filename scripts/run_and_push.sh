#!/usr/bin/env bash
# Run (or resume) a batch in 30-minute slices, committing and pushing results
# after each slice so nothing is lost if the machine goes away.
#   scripts/run_and_push.sh <tag> [extra run_batch args...]
#   SHARDS=2 scripts/run_and_push.sh <tag>     # 2 parallel workers on disjoint tasks
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="$1"; shift
PY=vendor/tau2-bench/.venv/bin/python
SHARDS="${SHARDS:-1}"
while true; do
  for i in $(seq 0 $((SHARDS - 1))); do
    timeout -s INT 30m "$PY" -m runner.run_batch --tag "$TAG" --shard "$i/$SHARDS" "$@" 2>&1 \
      | grep --line-buffered -E "task |\[$TAG\]|Stopped|Missing|Limits" | sed -u "s/^/[w$i] /" &
  done
  wait
  git add results/runs/"$TAG" results/cost_log.csv >/dev/null 2>&1
  if ! git diff --cached --quiet; then
    DONE=$(ls results/runs/"$TAG"/task_*.json 2>/dev/null | wc -l)
    git commit -q -m "results: $TAG progress ($DONE simulation files)"
    for i in 1 2 3 4; do git push -q origin HEAD 2>/dev/null && break; sleep $((i * 5)); done
  fi
  "$PY" -m runner.run_batch --tag "$TAG" "$@" --status 2>/dev/null | grep -q ", 0 pending" && { echo "ALL DONE"; break; }
  # Stop looping if the last slice hit a daily quota (needs a human or a later resume).
  [ -f results/.stop ] && { echo "stop file found"; break; }
done
