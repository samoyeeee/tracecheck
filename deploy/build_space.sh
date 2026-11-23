#!/usr/bin/env bash
# Assemble the Hugging Face Space repo in $1 (default: deploy/space): code, built
# web/site, config, Dockerfile. No results/ data beyond the web caches, no keys.
#   deploy/build_space.sh [out_dir]
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-deploy/space}"
mkdir -p "$OUT"
find "$OUT" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
for d in agent runner triage eval; do
  cp -r "$d" "$OUT/"
done
mkdir -p "$OUT/web" "$OUT/results"
cp web/__init__.py web/serve.py web/limits.py "$OUT/web/"
cp -r web/site "$OUT/web/"
cp config.yaml "$OUT/"
# caches that make the pre-analysed reports cheap to re-run (no user data)
cp -r results/translations "$OUT/results/" 2>/dev/null || true
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf {} +
cp deploy/Dockerfile "$OUT/Dockerfile"
cp deploy/README.space.md "$OUT/README.md"
printf '__pycache__/\n*.pyc\n' > "$OUT/.gitignore"
echo "Space files in $OUT ($(du -sh "$OUT" | cut -f1))"
