#!/bin/bash
# RepoProof Studio(Product Mode)— 仅本机访问,不开放局域网/公网。
# 默认在线智能功能与构建 Agent 均复用本机 Codex/ChatGPT 登录,无需加载 .env。
set -e
cd "$(dirname "$0")/.."
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
