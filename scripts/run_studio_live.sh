#!/bin/bash
# Product Studio 的旧 API/provider 兼容启动器。
#
# 当前缺省 `scripts/run_ui.sh` 已让摘要、在线起草、候选输入和真实构建全部
# 复用 Codex/ChatGPT 登录,无需 API key。只有显式设置
# `REPOPROOF_DRAFTER_BACKEND=litellm` 或选择 mini-swe 构建时才需要本脚本
# 从 gitignored .env 注入旧 provider 配置。密钥不写代码、不落日志、不进 argv。
#
# Lab UI 早就有对应脚本(run_lab_ui_live.sh,端口 8502),Product Studio
# 一直缺一个 —— 这就是那个缺口。
#
# 不使用旧 API/provider 时请直接运行 scripts/run_ui.sh。
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "缺少 .env(REPOPROOF_API_BASE/KEY/MODEL)——模型相关功能会被禁用," >&2
  echo "零模型的部分(仓库简介/离线起草/离线彩排)仍可正常使用。" >&2
fi
exec .venv/bin/streamlit run src/repoproof/ui/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false
