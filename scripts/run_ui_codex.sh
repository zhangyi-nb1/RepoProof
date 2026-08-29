#!/bin/bash
# RepoProof Studio 网关故障回退入口。
# 不加载 .env 里的私有网关密钥；摘要/起草/候选使用本机
# Codex/ChatGPT 登录。构建页仍保留 mini-swe 与 Codex CLI 双选项。
set -e
cd "$(dirname "$0")/.."
export REPOPROOF_DRAFTER_BACKEND=codex-cli
export REPOPROOF_DEFAULT_AGENT_BACKEND=codex-cli
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
