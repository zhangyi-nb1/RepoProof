#!/bin/bash
# 带模型连接的工作台启动:读取 RepoProof 自己的 .env(私密,已 gitignore)。
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
