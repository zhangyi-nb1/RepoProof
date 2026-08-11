#!/bin/bash
# T4 verify 台架:venv 外置、逐状态验证跑在抛弃式副本/scratch 上,栈本体零污染。
# 用法:
#   drive_t4.sh venvs                     # 从 wheelhouse 离线建 venv_s0 / venv_s1p
#   drive_t4.sh sidecar <root>            # 用特性自带脚本建 sidecar venv(一次)
#   drive_t4.sh verify <root> <features>  # features=逗号集(f1,f2,f3 的子集或 none)
#       在场特性跑其套件,缺席特性断言文件不存在;宿主回归计数按特性集推导。
# 退出码 0 = 全部通过。日志落 /tmp/_t4_eng/logs/。
set -uo pipefail
RP=/Users/zhangronglei/Desktop/XIANGMU/RepoProof
E=/tmp/_t4_eng
LOGS=$E/logs
WHEEL=$HOME/RepoProofBench/wheelhouse-offerclaw-5b2d00e
T2PKG=$RP/benchmarks/v2/tasks/t2_open_deep_research_v4
T3PKG=$RP/benchmarks/v2/tasks/t3_browser_use_v5
SIDE=$E/sidecar-venv
mkdir -p "$LOGS"

tmphygiene() {
  local t="${TMPDIR:-/tmp}"
  shopt -s nullglob
  rm -rf "$t"/rp_apply_assist_* "$t"/offerclaw-apply-* \
         "$t"/offerclaw_apply_assist_jobs "$t"/offerclaw_apply_assist_artifacts \
         "$t"/browser-use-user-data-dir-* "$t"/browseruse-* \
         "$t"/browser-use-downloads-* 2>/dev/null
  shopt -u nullglob
}

tailline() { grep -E "[0-9]+ (passed|failed)" "$1" | tail -1; }

case "${1:?phase}" in
  venvs)
    # 两个 venv 各自从零建。禁 cp 克隆 venv:脚本 shebang 是绝对路径,
    # 克隆体的 pip 会把包装回源 venv(实测污染过 venv_s0 基线)。
    for name in venv_s0 venv_s1p; do rm -rf "$E/$name"; done
    python3 -m venv "$E/venv_s0"
    "$E/venv_s0/bin/pip" install -q --no-index --find-links "$WHEEL" \
        -r "$HOME/RepoProofBench/offerclaw-transaction-stack/requirements.txt" \
        || { echo "venv_s0 FAILED"; exit 1; }
    python3 -m venv "$E/venv_s1p"
    "$E/venv_s1p/bin/pip" install -q --no-index --find-links "$WHEEL" \
        -r "$HOME/RepoProofBench/offerclaw-transaction-stack/requirements.txt" \
        "fastapi-mcp==0.4.0" "mcp==1.29.0" \
        || { echo "venv_s1p FAILED"; exit 1; }
    "$E/venv_s0/bin/python" -c "import fastapi_mcp" 2>/dev/null \
        && { echo "venv_s0 被污染(含 fastapi_mcp)"; exit 1; }
    "$E/venv_s1p/bin/python" -c "import fastapi_mcp, mcp" \
        || { echo "venv_s1p extras 缺失"; exit 1; }
    echo "venvs OK: $("$E/venv_s0/bin/python" -V) | s0 纯净 | s1p extras 就位"
    ;;
  sidecar)
    ROOT="${2:?sidecar 需要含构建脚本的树根}"
    rm -rf "$SIDE"
    bash "$ROOT/scripts/build_apply_assist_sidecar.sh" "$SIDE" \
        > "$LOGS/sidecar_build.log" 2>&1 \
        || { echo "sidecar build FAILED(见 $LOGS/sidecar_build.log)"; exit 1; }
    "$SIDE/bin/python" -c "import browser_use; from importlib.metadata import version; print('sidecar OK browser_use', version('browser-use'))" \
        || { echo "sidecar import FAILED"; exit 1; }
    ;;
  verify)
    ROOT="${2:?verify 需要树根}"
    FEATS="${3:?verify 需要特性集(如 f1,f2 或 none)}"
    TAG="${4:-$(basename "$ROOT")-$FEATS}"
    fail=0
    has() { case ",$FEATS," in *",$1,"*) return 0;; *) return 1;; esac; }

    # 在场/缺席矩阵(文件级)
    for spec in "f1:sdk_mcp.py" "f2:research_jobs.py" "f3:apply_assist.py"; do
      fid="${spec%%:*}"; marker="${spec##*:}"
      if has "$fid"; then
        [ -f "$ROOT/$marker" ] || { echo "MATRIX FAIL: $fid 应在场而 $marker 缺失"; fail=1; }
      else
        [ -f "$ROOT/$marker" ] && { echo "MATRIX FAIL: $fid 应缺席而 $marker 在场"; fail=1; }
      fi
    done

    PY="$E/venv_s0/bin/python"; EXPECT="606 passed"
    if has f1; then PY="$E/venv_s1p/bin/python"; EXPECT="609 passed"; fi

    (cd "$ROOT" && "$PY" -m pytest tests/ -q -p no:cacheprovider) \
        > "$LOGS/${TAG}_reg.log" 2>&1
    grep -q "$EXPECT" "$LOGS/${TAG}_reg.log" \
        || { echo "REGRESSION FAIL(期望 $EXPECT):$(tailline "$LOGS/${TAG}_reg.log")"; fail=1; }

    if has f2; then
      mkdir -p "$E/upstream" 2>/dev/null
      [ -d "$E/upstream/src" ] || cp -Rc "$RP/upstream-cache/upstream-20aaa0d422bd/." "$E/upstream/"
      # 栈层布局:<根>/../upstream;副本在 $E 下天然满足
      mkdir -p "$ROOT/public_tests_t2"
      cp "$T2PKG/public_tests/test_public_research.py" "$ROOT/public_tests_t2/"
      (cd "$ROOT" && OFFERCLAW_HOST_ROOT="$ROOT" \
          "$PY" -m pytest public_tests_t2/ -q -p no:cacheprovider) \
          > "$LOGS/${TAG}_t2pub.log" 2>&1
      # 只看 pytest 总结行(全文 grep 会误伤告警里的 errors.pydantic.dev)
      T2SUM=$(tailline "$LOGS/${TAG}_t2pub.log")
      case "$T2SUM" in
        *passed*) case "$T2SUM" in *failed*|*error*) \
            echo "T2 PUBLIC FAIL:$T2SUM"; fail=1;; esac;;
        *) echo "T2 PUBLIC FAIL:$T2SUM"; fail=1;;
      esac
    fi

    if has f3; then
      tmphygiene
      mkdir -p "$ROOT/public_tests" "$ROOT/fixtures"
      cp "$T3PKG/public_tests/test_public_apply_assist.py" "$ROOT/public_tests/"
      for f in fake_agent_llm.py mock_recruitment_site.py synthetic_resume.txt \
               test_mock_site_selfcheck.py; do
        cp "$T3PKG/fixtures/$f" "$ROOT/fixtures/"
      done
      [ -x "$SIDE/bin/python" ] || { echo "T3 verify 需先 drive_t4.sh sidecar"; exit 1; }
      (cd "$ROOT" && APPLY_ASSIST_SIDECAR_PYTHON="$SIDE/bin/python" \
          "$PY" -m pytest public_tests/ -q -p no:cacheprovider) \
          > "$LOGS/${TAG}_t3pub.log" 2>&1
      grep -q "23 passed" "$LOGS/${TAG}_t3pub.log" \
          || { echo "T3 PUBLIC FAIL(期望 23 passed):$(tailline "$LOGS/${TAG}_t3pub.log")"; fail=1; }
      pkill -f "remote-debugging-port" 2>/dev/null
      tmphygiene
    fi

    [ "$fail" -eq 0 ] && echo "VERIFY PASS [$TAG] feats=$FEATS reg=$(tailline "$LOGS/${TAG}_reg.log")"
    exit "$fail"
    ;;
  verify-last)
    # verify 的 root-last 变体:stack_ops rebuild 的 --verify-cmd 会把
    # scratch 路径附在命令末尾,故参数序 = feats tag root。
    FEATS="${2:?}"; TAG="${3:?}"; ROOT="${4:?}"
    exec bash "$0" verify "$ROOT" "$FEATS" "$TAG"
    ;;
  *) echo "unknown phase $1" >&2; exit 2 ;;
esac
