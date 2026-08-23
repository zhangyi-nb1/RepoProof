#!/bin/bash
# Benchmark Lab with model connections loaded from RepoProof's ignored .env.
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)。参考 README 或让助手生成。" >&2
fi
exec .venv/bin/streamlit run src/repoproof/ui/lab_app.py \
  --server.address 127.0.0.1 \
  --server.port 8502 \
  --server.headless true \
  --browser.gatherUsageStats false
