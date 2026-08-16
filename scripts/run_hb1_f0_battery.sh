#!/usr/bin/env bash
# HB-PCDELTA-1 §10 前置第 4 项:F0 电池(冒烟,不计模型表现)。
#
# 每题四形态,顺序跑(并发会让回归套件互相拖慢,超时读数失真):
#   positive              → PASS_ADAPTED(delta 全绿 + 回归零破坏 + 重放一致)
#   nc_null_submission    → FAIL / IMPL_INCOMPLETE
#   nc_regression_break   → FAIL / REGRESSION_BROKEN
#   nc_instrument_tamper  → FAIL / INSTRUMENT_TAMPERED(附录一第 9 条新增)
#
# 一题四发全绿才进下一题(预注册 §10:撞出的管线缺陷修完才进下一题)。
# 判定不在本脚本 —— 本脚本只负责跑与留痕,红绿由 scripts/hb_batch_criteria.py
# 读台账裁定(脚本不自证自己跑对了)。
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
BATCH=HB-PCDELTA1-F0-R3          # R3 = skipped≠failed 同病扫查修复后的重跑
FORMS=(positive control:nc_null_submission control:nc_regression_break control:nc_instrument_tamper)
TASKS=(hb1_click_3581 hb1_click_3407 hb1_sqlglot_8042)

mkdir -p /tmp/rp_f0_r3
idx=0
for t in "${TASKS[@]}"; do
  for f in "${FORMS[@]}"; do
    idx=$((idx + 1))
    tag="${t}__${f//:/_}"
    echo "=== [$idx] $tag ==="
    $PY -m repoproof.cli host-run \
        --contract "benchmarks/v2/tasks/$t/contract.yaml" \
        --fake "$f" --batch "$BATCH" --run-order 0 --run-index "$idx" \
        > "/tmp/rp_f0_r3/$tag.log" 2>&1
    rc=$?
    echo "    exit=$rc  日志 /tmp/rp_f0_r3/$tag.log"
    tail -3 "/tmp/rp_f0_r3/$tag.log" | sed 's/^/    /'
  done
  echo "=== $t 四形态跑完 ==="
done
echo "=== 电池跑完;红绿裁定见 hb_batch_criteria.py --batch $BATCH ==="
