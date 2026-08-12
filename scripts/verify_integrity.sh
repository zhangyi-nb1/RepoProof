#!/usr/bin/env bash
# 一键完整性验证(PROCESS-INDEPENDENCE-PLAN §5):任何一环非零即整体非零。
# 这三环的共同点:结论由机器判,不由散文判。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/3 闸门数字一致性(台账重算 vs docs/v2_gate.json)=="
.venv/bin/python scripts/gate_report.py --check

echo "== 2/3 公开声明一致性(散文数字 vs 事实源;禁词扫描)=="
.venv/bin/python scripts/check_public_claims.py

echo "== 3/3 变异闸门(历史缺陷注回源码,钉死套件必须 100% 抓住)=="
.venv/bin/python scripts/mutation_gate.py

echo "全部通过。"
