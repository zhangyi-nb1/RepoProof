#!/bin/bash
# Product Studio,带上模型连接配置(从被 gitignore 的 .env 注入)。
#
# 为什么需要这个脚本(2026-08-27 用户实测):Studio 直接
# `streamlit run` 起来时,进程里没有 REPOPROOF_* —— 于是"让模型总结"、
# 非离线起草、真发构建**全都会报"起草通道未配置"**,而 .env 明明就在
# 仓库根。密钥按纪律只经 `set -a; source .env; set +a` 注入进程环境,
# 不写进代码、不落进日志、不进 argv。
#
# Lab UI 早就有对应脚本(run_lab_ui_live.sh,端口 8502),Product Studio
# 一直缺一个 —— 这就是那个缺口。
#
# 只想跑零模型的部分(读仓库简介、离线模板起草、离线彩排)时,不用这个
# 脚本也可以:UI 会检测到没有连接配置,并在模型相关的入口旁给出提示。
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
