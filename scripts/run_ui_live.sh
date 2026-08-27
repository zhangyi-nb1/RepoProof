#!/bin/bash
# API/provider 启动器（与 run_ui.sh 相同的默认通道）。
# 密钥仅进进程环境——不写日志、不进 UI、不进任何产物。
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)。参考 README 或让助手生成。" >&2
fi
export REPOPROOF_DRAFTER_BACKEND="${REPOPROOF_DRAFTER_BACKEND:-litellm}"
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
