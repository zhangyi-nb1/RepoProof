#!/bin/bash
# 冷启动简报(SessionStart hook):每个新会话——**包括压缩后自动产生的
# 新会话**——自动注入磁盘上的真实进度。
#
# 存在理由(TESTPLAN §1.2):自动压缩的摘要是通用的、会失真(实证:协作
# 会话把 T2 记成前沿而磁盘已在 T3v2,连续两次凭记忆报错进度)。本钩子
# 让"换壳"从"省钱但可能变笨"变成"省钱且不会记错"——进度事实永远
# 来自磁盘,不来自摘要。
#
# 纪律:只读;输出保持精简(百来行以内),避免抵消换壳省下的上下文。
set -euo pipefail
cd "$(dirname "$0")/../.." || exit 0

LOG=docs/EXPLORATION_LOG.md
RUNS=benchmarks/v2/runs.jsonl

BRIEF=$(
  echo "【磁盘取证简报 · 自动注入,进度以此为准而非摘要记忆】"
  echo
  echo "最近提交:"
  git log --oneline -3 2>/dev/null | sed 's/^/  /'
  echo
  if [ -f "$RUNS" ]; then
    echo "runs.jsonl:$(wc -l < "$RUNS" | tr -d ' ') 行;最后一发:"
    tail -1 "$RUNS" | python3 -c "import sys,json;r=json.load(sys.stdin);print('  ',r.get('run_id'),'|',r.get('model'),'|',r.get('verdict'))" 2>/dev/null || true
    echo
  fi
  PREREG=$(ls -t benchmarks/v2/preregistrations/*.md 2>/dev/null | head -1)
  [ -n "$PREREG" ] && echo "最新预注册:$PREREG" && echo
  if [ -f "$LOG" ]; then
    echo "最新状态条目(EXPLORATION_LOG 尾部):"
    awk '/^## /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$LOG" | head -40 | sed 's/^/  /'
  fi
  echo
  echo "冷启动仍按 TESTPLAN §0 顺序补齐;有疑先查盘,勿凭记忆断言进度。"
)

python3 - "$BRIEF" <<'PY'
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": sys.argv[1],
}}, ensure_ascii=False))
PY
