"""语义指纹分面的钉死(2026-08-14 用户指令:按语义所有权划,不按目录划)。

**问题**:S1 的 `exec_fingerprint` 把整个 `src/repoproof/**` 当成"执行器",
于是修一个冒烟脚本、收窄一个扫描边界,都会让**全部历史发次跨代失配**。
它保守,但会造成大量无意义的不可比。

**分面(按谁拥有这段语义,不按它住在哪个目录)**:

    executor_semantics   改了它 = **被测系统变了**。判据:是否改变
                         模型可见内容 / 工具行为 / 命令执行 / 运行预算。
                         例:context_projector(投影)、repoproof_env(工具)、
                         token_budget(预算)、backend(循环)。
    model_profile        provider / 采样 / 动作协议。例:provider_gate。
    verifier             独立验证与完整性扫描。例:verification/、
                         harness/oracle_guard、host_guard、postflight。
    instrumentation      量具与实验校准 —— **改它不改变被测系统**。
                         例:profiles(指纹本身)、persistence(记账)、
                         fake_model(冒烟脚本)。
    task                 任务包内容(冻结契约/oracle/控制组)。不在 src 下。
    analysis_schema      分析口径版本号,人工递增。

**冻结判据**(先写判据与反例;措辞此后不改):

- F1 **分面互斥且穷尽**:`src/repoproof/**` 的每个 .py 恰好归一面。反例:
  漏一个模块 → 它变了却没有任何指纹反映,跨代比较悄悄失真。
- F2 **只有 executor 面的改动才改 `executor_semantics_fingerprint`**。
  反例:修 `fake_model.py` 的冒烟脚本(纯实验校准)却让执行器指纹变,
  于是批 14 的 A 臂再也补不了发 —— 那是**无意义的跨代失配**。
- F3 **归属由语义决定,不由目录决定**。`agents/` 下既有 executor 面
  (`context_projector`)也有 instrumentation 面(`profiles`)。反例:
  按目录一刀切 → `profiles.py` 这种纯量具被算成执行语义。
- F4 **可比性判定按面**:两发是否可做严格 A/B,只看**相关面**是否同指纹,
  不要求全部面相同。反例:要求所有面逐字节相同 → 修一个错别字就让整批
  历史作废。
- F5 **旧发次不追溯**:已有 `exec_fingerprint` 的发次保留原值,新发次记
  新分面。反例:回填旧发次 → 那是编造它们当时并不存在的事实。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.agents.profiles import (
    FACES,
    comparable_for,
    face_of,
    semantic_fingerprints,
)

REPO = Path(__file__).resolve().parents[1]


def test_every_module_belongs_to_exactly_one_face():
    """F1:分面互斥且穷尽 —— 漏一个模块,它变了却没指纹反映。"""
    root = REPO / "src" / "repoproof"
    orphans = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        if face_of(rel) is None:
            orphans.append(rel)

    assert not orphans, f"这些模块没有语义归属,跨代比较会悄悄失真:{orphans}"


def test_faces_are_disjoint():
    """F1 的另一半:一个模块不得同时属于两面。"""
    root = REPO / "src" / "repoproof"
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        hits = [f for f in FACES if face_of(rel) == f]
        assert len(hits) == 1, f"{rel} 归属不唯一:{hits}"


def test_instrumentation_change_does_not_move_executor_fingerprint(tmp_path):
    """F2:改量具不改被测系统 —— 这是重划的**全部理由**。"""
    root = tmp_path / "src" / "repoproof"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "context_projector.py").write_text("EXEC = 1\n")
    (root / "agents" / "profiles.py").write_text("INSTR = 1\n")
    (root / "agents" / "fake_model.py").write_text("SMOKE = 1\n")

    before = semantic_fingerprints(tmp_path)
    (root / "agents" / "fake_model.py").write_text("SMOKE = 2\n")     # 纯实验校准
    after = semantic_fingerprints(tmp_path)

    assert after["executor_semantics_fingerprint"] == before["executor_semantics_fingerprint"], (
        "改冒烟脚本却让执行器指纹变了 —— 历史发次被无意义地判为跨代")
    assert after["instrumentation_fingerprint"] != before["instrumentation_fingerprint"], (
        "量具变了却没有任何指纹反映")


def test_executor_change_does_move_executor_fingerprint(tmp_path):
    """F2 的另一面:真改执行语义必须反映出来。"""
    root = tmp_path / "src" / "repoproof"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "context_projector.py").write_text("EXEC = 1\n")
    (root / "agents" / "profiles.py").write_text("INSTR = 1\n")

    before = semantic_fingerprints(tmp_path)
    (root / "agents" / "context_projector.py").write_text("EXEC = 2\n")
    after = semantic_fingerprints(tmp_path)

    assert after["executor_semantics_fingerprint"] != before["executor_semantics_fingerprint"]
    assert after["instrumentation_fingerprint"] == before["instrumentation_fingerprint"]


def test_face_assignment_is_semantic_not_directory_based():
    """F3:同一目录下可以分属不同面。"""
    assert face_of("agents/context_projector.py") == "executor_semantics"
    assert face_of("agents/profiles.py") == "instrumentation"
    assert face_of("agents/provider_gate.py") == "model_profile"
    assert face_of("agents/fake_model.py") == "instrumentation"


def test_verifier_face_covers_integrity_scans():
    """F3:验证与完整性扫描归 verifier —— h4 那类扫描边界改动落这里。"""
    assert face_of("verification/bundle_check.py") == "verifier"
    assert face_of("harness/oracle_guard.py") == "verifier"
    assert face_of("harness/host_guard.py") == "verifier"


def test_comparability_is_per_face():
    """F4:严格 A/B 只看相关面,不要求全部面相同。"""
    a = {"executor_semantics_fingerprint": "X", "instrumentation_fingerprint": "1",
         "verifier_fingerprint": "V", "model_profile_fingerprint": "M"}
    b = {"executor_semantics_fingerprint": "X", "instrumentation_fingerprint": "2",
         "verifier_fingerprint": "V", "model_profile_fingerprint": "M"}

    assert comparable_for(a, b, faces=("executor_semantics",)), (
        "执行语义相同却判不可比 —— 修个错别字就让整批历史作废")
    assert not comparable_for(a, b, faces=("instrumentation",))


def test_real_repo_reports_all_faces():
    """接线检查:真仓能算出全部分面,且都是 16 位十六进制。"""
    got = semantic_fingerprints(REPO)

    for f in FACES:
        key = f"{f}_fingerprint"
        assert key in got, f"缺分面 {key}"
        assert len(got[key]) == 16 and all(c in "0123456789abcdef" for c in got[key])
    assert isinstance(got["analysis_schema_version"], int)


# ------------------------------------------------- 三处缺陷修复的分面归属
# 2026-08-14:第 2 步修 fake-positive smoke / h4 / _cmd_of。重划分面的
# **验收就在这里** —— 这三处各属不同语义面,修完执行语义指纹应当:
#   fake-positive smoke → instrumentation(实验校准,不改被测系统)
#   h4 扫描边界        → verifier(独立验证的扫描范围)
#   _cmd_of            → executor_semantics(它喂投影,投影改模型可见内容)
# 前两处**不该**让 executor_semantics 变动。这条钉死把归属写死。

def test_the_three_step2_fixes_land_on_the_right_faces():
    """第 2 步三处修复的语义归属 —— 重划分面的直接验收。"""
    assert face_of("agents/fake_model.py") == "instrumentation", (
        "冒烟脚本属实验校准 —— 修它不该让历史发次跨代")
    assert face_of("harness/oracle_guard.py") == "verifier", (
        "oracle 扫描边界属验证面")
    assert face_of("agents/context_projector.py") == "executor_semantics", (
        "_cmd_of 喂投影,投影改变模型可见内容 —— 属执行语义")


def test_smoke_script_fix_would_not_invalidate_history(tmp_path):
    """F2 的现场版:改冒烟脚本后,执行语义指纹必须纹丝不动。

    反例正是重划前的行为 —— 修一个 T1 专用的文件名就让批 14 的 A 臂
    再也补不了发。"""
    root = tmp_path / "src" / "repoproof"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "fake_model.py").write_text("SCRIPT = 'sdk_mcp.py'\n")
    (root / "agents" / "repoproof_env.py").write_text("ENV = 1\n")

    before = semantic_fingerprints(tmp_path)
    (root / "agents" / "fake_model.py").write_text("SCRIPT = 'from manifest'\n")
    after = semantic_fingerprints(tmp_path)

    assert after["executor_semantics_fingerprint"] == before["executor_semantics_fingerprint"]
    assert after["instrumentation_fingerprint"] != before["instrumentation_fingerprint"]
