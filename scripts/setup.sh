#!/usr/bin/env bash
# Clone the two upstream repos (pinned) and install tau2 into vendor/tau2-bench/.venv
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p vendor
[ -d vendor/tau2-bench ] || git clone https://github.com/sierra-research/tau2-bench.git vendor/tau2-bench
(cd vendor/tau2-bench && git fetch --depth 1 origin c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4 && git checkout -q c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4 && uv sync && uv pip install pytest)
[ -d vendor/agentrx ] || git clone https://github.com/microsoft/agentrx.git vendor/agentrx
echo "Done. Run things with: vendor/tau2-bench/.venv/bin/python -m runner.run_batch --help"
