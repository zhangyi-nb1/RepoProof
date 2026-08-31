#!/usr/bin/env bash
# 唯一构建声明(harness 锁定件)。clean replay 与用户安装走同一条路。
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -q -r requirements.lock.txt
.venv/bin/pip install --disable-pip-version-check -q -e .
echo "build ok: $(pwd)"
