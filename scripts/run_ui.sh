#!/bin/bash
# RepoProof Studio(Product Mode)— 仅本机访问,不开放局域网/公网。
# 缺省恢复为 API 网关 + mini-swe；网关故障时用 run_ui_codex.sh。
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)——在线网关功能不可用。" >&2
fi
export REPOPROOF_DRAFTER_BACKEND="${REPOPROOF_DRAFTER_BACKEND:-litellm}"
# GPT-5-compatible gateways differ on whether temperature=0 is accepted, and
# LiteLLM may reject the parameter client-side before the provider sees it.
# Product Mode therefore binds both preflight and the real run to provider default.
export REPOPROOF_TEMPERATURE_POLICY="${REPOPROOF_TEMPERATURE_POLICY:-provider_default}"
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
