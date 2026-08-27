"""上游 pin 单一来源(LESSONS #52)—— 那份锁必须**一定存在**。

来由:webcolors 连跑四发全 FAIL,死于 `ModuleNotFoundError`。链条是
`reference.lock.txt` 标着"(可选)"却缺席 → 三处各自静默降级(装配不写
controls 锁 / 备轮不下上游 / positive 彩排不预装)→ `import <上游>` 必炸,
还要等三轮修复耗尽才以 DEPENDENCY_ERROR 浮出来。

所以这里钉的不是某一处补丁,而是**那份锁在缺草稿件时也会被派生出来**。
"""

from __future__ import annotations

import re
from pathlib import Path

from repoproof.adoption.intake.upstream_pin import (
    derive_reference_lock,
    normalize_dist_name,
    upstream_version,
)

_COMMIT = "e6392ba6eeba81b02e666eb3ed02ef2e006344c0"


def _tree(project_root: Path, body: str, *, name: str = "pyproject.toml") -> Path:
    """按 upstream-cache/upstream-<commit12> 的真实约定摆树。

    夹具必须与生产同构:第一版把树摆在 tmp 根,派生自然找不到 ——
    那样测出来的"读不出版本"是夹具的锅,不是被测件的行为。
    """
    up = project_root / "upstream-cache" / f"upstream-{_COMMIT[:12]}"
    up.mkdir(parents=True, exist_ok=True)
    (up / name).write_text(body, encoding="utf-8")
    return up


def test_version_from_pep621_setupcfg_and_pkginfo(tmp_path: Path):
    a = _tree(tmp_path / "a", '[project]\nname = "x"\nversion = "25.10.0"\n')
    assert upstream_version(a) == "25.10.0"

    b = _tree(tmp_path / "b", "[metadata]\nversion = 1.2.3\n", name="setup.cfg")
    assert upstream_version(b) == "1.2.3"

    c = tmp_path / "c" / "upstream-cache" / f"upstream-{_COMMIT[:12]}" / "x.egg-info"
    c.mkdir(parents=True)
    (c / "PKG-INFO").write_text("Name: x\nVersion: 0.9\n", encoding="utf-8")
    assert upstream_version(c.parent) == "0.9"


def test_dynamic_version_is_not_guessed(tmp_path: Path):
    """**负控**:动态版本读不出就是读不出 —— 不猜、不去 PyPI 拿最新版。

    pin 的语义是"就这一版";解析最新版等于把钉版偷偷放开。
    """
    up = _tree(tmp_path, '[project]\nname = "x"\ndynamic = ["version"]\n')
    assert upstream_version(up) == ""
    assert derive_reference_lock(
        tmp_path, distribution="x",
        resolved_commit=_COMMIT) == ""


def test_derived_lock_carries_the_pin_and_its_provenance(tmp_path: Path):
    _tree(tmp_path, '[project]\nname = "webcolors"\nversion = "25.10.0"\n')
    lock = derive_reference_lock(
        tmp_path, distribution="webcolors",
        resolved_commit=_COMMIT)
    assert "webcolors==25.10.0" in lock
    assert "e6392ba6eeba" in lock          # 说得出出处
    assert "以你写的为准" in lock            # 人写的优先,写在文件里


def test_dist_name_normalisation_is_pep503():
    assert normalize_dist_name("Foo_Bar.baz") == "foo-bar-baz"
    assert normalize_dist_name(" webcolors ") == "webcolors"


# ------------------------- 审核页必须**看得见**依赖锁(UI 侧的同一课)

def test_review_bundle_exposes_dependency_lock(tmp_path: Path, monkeypatch):
    """草稿审核件要带依赖锁状态 —— 这是用户唯一能提前发现问题的地方。

    2026-08-28 实测:GAPS.md 白纸黑字写着 `reference_lock(owner=AUTO):
    由 pip 冻结闭包生成`,但没有任何组件真的生成它;审核页也从不显示它。
    于是用户按 UI 说的每一步都做了,仍然连拿四发必崩的构建 —— **系统
    承诺了没兑现,而且不给人看见的机会**。
    """
    from repoproof.ui.services import product_jobs

    state = tmp_path / "state"
    draft = state / "drafts" / "d1"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        "tool:\n  name: demo-tool\n"
        "source_repo:\n  distribution: webcolors\n"
        f"  resolved_commit: {_COMMIT}\n", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text("# demo\n", encoding="utf-8")
    _tree(tmp_path / "repo", '[project]\nname = "webcolors"\nversion = "25.10.0"\n')

    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr("repoproof.ui.services.product_mode.project_root",
                        lambda: tmp_path / "repo")

    got = product_jobs.read_managed_draft_review(draft)
    assert got["ok"], got.get("error")
    lock = got["dependency_lock"]
    assert lock["source"] == "derived"
    assert lock["pins"] == ["webcolors==25.10.0"]


def test_review_bundle_says_missing_when_nothing_can_be_derived(tmp_path: Path, monkeypatch):
    """**负控**:派生不出来时如实说"缺",并给出该写什么 —— 不装作没事。"""
    from repoproof.ui.services import product_jobs

    state = tmp_path / "state"
    draft = state / "drafts" / "d2"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        "tool:\n  name: demo-tool\n"
        "source_repo:\n  distribution: mystery\n"
        f"  resolved_commit: {_COMMIT}\n", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text("# demo\n", encoding="utf-8")

    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr("repoproof.ui.services.product_mode.project_root",
                        lambda: tmp_path / "repo")

    lock = product_jobs.read_managed_draft_review(draft)["dependency_lock"]
    assert lock["source"] == "missing" and lock["pins"] == []
    assert "reference.lock.txt" in lock["note"]


# ---------------- 全量核账:每条声明的缺口都必须有履行者(2026-08-28) ----------------

def test_every_declared_gap_has_a_fulfiller():
    """**制度钉**:GAPS 里每条 owner 都得有人真的履行。

    这一课的来由:`reference_lock` 标着 owner=AUTO(系统生成),却没有
    任何组件真的生成 —— 用户按 UI 每一步都做对,仍连拿四发必崩的构建。
    "声明了责任、没有履行者"是一类病,不是一个 bug,所以在这里钉住:

      owner=LLM  → 必须在起草器的字段白名单里;
      owner=AUTO → 必须有确定性产出路径(此处即上游 pin 派生);
      owner=USER → 必须在 UI 有填写入口(见下一条钉)。
    """
    import inspect

    from repoproof.adoption.intake import tool_intake
    from repoproof.adoption.intake.tool_drafter import _LLM_FIELDS

    src = inspect.getsource(tool_intake)
    declared = re.findall(r'DraftGap\(field="([^"]+)",\s*owner="([^"]+)"', src)
    assert declared, "一条缺口都没扫到 —— 钉子自身失效"

    llm = {f for f, o in declared if o == "LLM"}
    assert llm <= set(_LLM_FIELDS), f"标了 owner=LLM 但起草器不填:{llm - set(_LLM_FIELDS)}"

    auto = {f for f, o in declared if o == "AUTO"}
    assert auto <= {"reference_lock"}, (
        f"新增了 owner=AUTO 缺口 {auto - {'reference_lock'}} —— "
        "必须同时给出确定性产出路径,并在这里登记(否则又是一次'承诺没兑现')")


def test_user_owned_source_fields_are_editable_in_the_ui():
    """owner=USER 的上游身份三件必须能在审核页填 —— 否则提取失败即死路。

    实录:它们标着 owner=USER,但审核页没有入口、save_draft_review 也不
    收,Studio 用户只能去手改 draft.yaml。
    """
    import inspect

    from repoproof.ui.services import product_jobs

    sig = inspect.signature(product_jobs.save_draft_review).parameters
    for field in ("distribution", "import_module", "license_id"):
        assert field in sig, f"save_draft_review 不收 {field},UI 就没法让人填"

    page = (Path(__file__).resolve().parents[1] / "src" / "repoproof" / "ui"
            / "pages" / "tool_onboarding.py").read_text(encoding="utf-8")
    for probe in ("distribution=distribution", "import_module=import_module",
                  "license_id=license_id"):
        assert probe in page, f"审核页没把 {probe} 传下去"


# ---------------- 保存不许把起草成果抹白(2026-08-28 用户截图实录) ----------------

def _managed_draft(tmp_path: Path, monkeypatch, *, summary: str) -> Path:
    from repoproof.ui.services import product_jobs

    state = tmp_path / "state"
    draft = state / "drafts" / "d"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        "tool:\n  name: demo-tool\n"
        f"  summary: {summary}\n"
        "  interface:\n    input: {format: TEXT}\n"
        "    output: {format: JSON}\n"
        "capability:\n  statement: 原有的能力陈述\n  output_schema: DemoOut\n"
        "source_repo:\n  distribution: webcolors\n"
        f"  resolved_commit: {_COMMIT}\n", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    return draft


def test_save_refuses_to_blank_out_drafted_fields(tmp_path: Path, monkeypatch):
    """**保命闸**:提交上来的空值不许覆盖已有内容。

    实录:Streamlit 控件值是首次渲染时定的 —— 用户在草稿还空着时打开审核页,
    控件记住空值;起草器随后填满草稿,页面仍显示空白。此时点「保存」就会把
    起草成果抹掉,而用户看不见自己抹了什么。清空不是一种编辑意图。
    """
    from repoproof.ui.services import product_jobs

    draft = _managed_draft(tmp_path, monkeypatch, summary="起草器写的摘要")
    got = product_jobs.save_draft_review(
        draft, tool_name="demo-tool", summary="", statement="",
        input_format="", output_format="", output_schema="",
        reference_impl="# demo\n")

    assert not got["ok"]
    assert "拒绝保存" in got["error"] and "一句话摘要" in got["error"]
    # 盘上内容一字未动
    assert "起草器写的摘要" in (draft / "draft.yaml").read_text(encoding="utf-8")


def test_save_still_accepts_a_real_edit(tmp_path: Path, monkeypatch):
    """正控:真编辑照常放行 —— 闸拦的是"抹白",不是"修改"。"""
    from repoproof.ui.services import product_jobs

    draft = _managed_draft(tmp_path, monkeypatch, summary="旧摘要")
    got = product_jobs.save_draft_review(
        draft, tool_name="demo-tool", summary="新摘要", statement="新的能力陈述",
        input_format="TEXT", output_format="JSON", output_schema="DemoOut",
        reference_impl="# demo\n")
    assert got.get("ok"), got
    assert "新摘要" in (draft / "draft.yaml").read_text(encoding="utf-8")
