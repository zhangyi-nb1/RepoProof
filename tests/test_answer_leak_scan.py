"""答案泄漏扫描的钉死(盲攻前置自证,prereg-v2 §5 prep)。

上一轮这一步是**手工**做的:`leak-scan-round2.json` 只留下两个数字,没留下
可重跑的判据。本文件把判据钉住:

    L1  自校准 —— parent 已有行不算指纹(攻击者合法可见整棵 parent,
        不减 parent 会把每个候选都误杀);
    L2  长度门槛 —— 样板短行没有识别力,当指纹只制造假阳性;
    L3  规范化 —— 缩进/空白差异不该让同一行躲过扫描(泄漏检测被格式打败
        是最没道理的漏法);
    L4  **没扫 ≠ 干净**:scan=None 判死(M69c / H6c 同律);
    L5  **自证死 = 判死**:种植指纹没被逮住时,"命中 0"与"根本没扫"在证据上
        不可分辨;
    L6  **指纹 0 = 判死**:校准不出指纹说明尺子没搭上被测面;
    L7  命中即判死;
    L8  标定证据留痕。

**扫描面的定语**(实测教训,别丢):可扫的是**攻击前**交给攻击者的那份树。
封存池里的 `attacks/<cid>/delivery` 是**攻击后**的树 —— 它含攻击者自己写的
实现,拿它当扫描面会把"攻击者独立想到了同一个函数名"读成"答案泄漏"
(click-3581 实测:`def custom_version_option(` 在攻击后树里命中,而那一发
的实测比分是 0/3,攻击者根本没做对)。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "answer_leak_scan", REPO / "scripts" / "answer_leak_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LONG_A = "def preserve_unmatched_rows(self, side, matched_indexes):"
_LONG_B = "return [row for row in rows if row not in matched_indexes]"


def test_l1_parent_lines_are_not_fingerprints() -> None:
    als = _load()
    patch = f"+++ b/x.py\n+{_LONG_A}\n+{_LONG_B}\n"
    # parent 上已有 A → 只有 B 算指纹
    fps = als.calibrate_fingerprints(patch, {_LONG_A})
    assert fps == [_LONG_B], fps
    # parent 上两条都有 → 一条指纹都不该出(自校准的极端情形)
    assert als.calibrate_fingerprints(patch, {_LONG_A, _LONG_B}) == []


def test_l2_short_boilerplate_lines_are_not_fingerprints() -> None:
    als = _load()
    assert als.MIN_FINGERPRINT_LEN == 24
    patch = "+++ b/x.py\n+    return None\n+        continue\n+    else:\n"
    assert als.calibrate_fingerprints(patch, set()) == []


def test_l3_whitespace_differences_do_not_hide_a_leak() -> None:
    als = _load()
    fps = als.calibrate_fingerprints(f"+++ b/x.py\n+    {_LONG_A}\n", set())
    assert fps == [_LONG_A]                      # 校准侧已规范化
    hits = als.scan_documents(fps, {"statement.md": f"\t\t{_LONG_A}   \n"})
    assert [h["where"] for h in hits] == ["statement.md"], hits


def test_l4_unscanned_is_not_clean() -> None:
    als = _load()
    ok, problems = als.judge_leak_scan(None)
    assert not ok and any("没扫" in p for p in problems), problems


def test_l5_dead_selfcheck_is_refused() -> None:
    als = _load()
    ok, problems = als.judge_leak_scan(
        {"fingerprints_calibrated": 10, "leak_hits": [],
         "selfcheck_planted_detected": False})
    assert not ok and any("自证" in p for p in problems), problems
    # 自证本身必须是真的在跑:有指纹 → 活;无指纹 → 死(不造真)
    assert als.selfcheck([_LONG_A]) is True
    assert als.selfcheck([]) is False


def test_l6_zero_fingerprints_is_refused() -> None:
    als = _load()
    ok, problems = als.judge_leak_scan(
        {"fingerprints_calibrated": 0, "leak_hits": [],
         "selfcheck_planted_detected": True})
    assert not ok and any("尺子" in p for p in problems), problems


def test_l7_any_hit_kills() -> None:
    als = _load()
    scan = {"fingerprints_calibrated": 10, "selfcheck_planted_detected": True,
            "leak_hits": [{"fingerprint": _LONG_A, "where": "statement.md", "line": 3}]}
    ok, problems = als.judge_leak_scan(scan)
    assert not ok and any("盲攻不成立" in p for p in problems), problems
    # 干净面 → 过
    ok, problems = als.judge_leak_scan(
        {"fingerprints_calibrated": 10, "leak_hits": [],
         "selfcheck_planted_detected": True})
    assert ok, problems


def test_l8_window2_calibration_evidence_is_on_disk() -> None:
    ev = json.loads((REPO / "docs/evidence/d5_hunt/leak-scan-window2.json")
                    .read_text(encoding="utf-8"))
    rec = ev["sqlglot-7953"]
    assert rec["selfcheck_planted_detected"] is True
    assert rec["fingerprints_calibrated"] > 0
    assert rec["leak_hits"] == []
    assert rec["verdict"]["ok"] is True
