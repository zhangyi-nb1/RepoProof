#!/bin/bash
# 带模型连接的工作台启动(Gate 9B):从本地既有配置注入 REPOPROOF_*,
# 密钥仅存在于进程环境——不写文件、不进 UI、不进日志。
set -e
cd "$(dirname "$0")/.."
eval "$(.venv/bin/python /tmp/rp_env.py 2>/dev/null || true)"
if [ -z "$REPOPROOF_API_KEY" ]; then
  echo "未找到模型连接配置(REPOPROOF_API_KEY)。请先准备 /tmp/rp_env.py 或手动 export。" >&2
fi
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 --server.headless true \
  --browser.gatherUsageStats false
