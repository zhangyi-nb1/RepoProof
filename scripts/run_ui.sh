#!/bin/bash
# RepoProof Studio(Product Mode)— 仅本机访问,不开放局域网/公网。
set -e
cd "$(dirname "$0")/.."
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
