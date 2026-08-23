#!/bin/bash
# RepoProof Benchmark Lab — preserved experiments and historical records.
set -e
cd "$(dirname "$0")/.."
exec .venv/bin/streamlit run src/repoproof/ui/lab_app.py \
  --server.address 127.0.0.1 \
  --server.port 8502 \
  --server.headless true \
  --browser.gatherUsageStats false
