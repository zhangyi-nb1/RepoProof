#!/bin/bash
# 旧 API/provider 兼容启动器；缺省 Codex 订阅路径请用 run_ui.sh。
# 密钥仅进进程环境——不写日志、不进 UI、不进任何产物。
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)。参考 README 或让助手生成。" >&2
fi
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
