#!/bin/bash
# Product Studio 默认启动器：从 gitignored .env 注入 API 网关配置。
#
# 摘要、在线起草和候选输入默认走 LiteLLM/API 网关，真实构建
# 默认选 mini-swe。密钥不写代码、不落日志、不进 argv。
#
# Lab UI 早就有对应脚本(run_lab_ui_live.sh,端口 8502),Product Studio
# 一直缺一个 —— 这就是那个缺口。
#
# 网关故障时可改用 scripts/run_ui_codex.sh，它保留当前 Codex 订阅路径。
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)——模型相关功能会被禁用," >&2
  echo "零模型的部分(仓库简介/离线起草/离线彩排)仍可正常使用。" >&2
fi
export REPOPROOF_DRAFTER_BACKEND="${REPOPROOF_DRAFTER_BACKEND:-litellm}"
export REPOPROOF_TEMPERATURE_POLICY="${REPOPROOF_TEMPERATURE_POLICY:-provider_default}"
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
