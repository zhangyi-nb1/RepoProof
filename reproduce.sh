#!/usr/bin/env bash
# RepoProof Gate 2 — reproduce the full evidence chain end to end.
# Requires: docker daemon reachable (colima start), python 3.12, network
# for the install phase (contract: network_install=true, network_test=false).
set -euo pipefail
cd "$(dirname "$0")"

CONTRACT="contracts/adopt-chonkie-local-chunking-v2.yaml"

echo "== [1/5] docker daemon =="
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'

echo "== [2/5] python env =="
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install --disable-pip-version-check -q -e ".[dev]"
fi
.venv/bin/python --version

echo "== [3/5] host unit tests =="
.venv/bin/pytest -q

echo "== [4/5] contract freeze check =="
shasum -a 256 -c "${CONTRACT}.sha256"

echo "== [5/6] direct-adoption baseline (+ baseline_failure_reproduction replay) =="
.venv/bin/python -m repoproof.cli baseline --contract "$CONTRACT"

echo "== [6/6] bundle integrity =="
LATEST=$(ls -t runs | head -1)
.venv/bin/python -m repoproof.cli verify-bundle --run-dir "runs/$LATEST" --contract "$CONTRACT"

echo "Done. Evidence in runs/$LATEST (report.json / run_manifest.json / trace.jsonl)."
