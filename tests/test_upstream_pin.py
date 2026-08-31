"""上游 pin 单一来源(LESSONS #52)—— 那份锁必须**一定存在**。

来由:webcolors 连跑四发全 FAIL,死于 `ModuleNotFoundError`。链条是
`reference.lock.txt` 标着"(可选)"却缺席 → 三处各自静默降级(装配不写
controls 锁 / 备轮不下上游 / positive 彩排不预装)→ `import <上游>` 必炸,
还要等三轮修复耗尽才以 DEPENDENCY_ERROR 浮出来。

所以这里钉的不是某一处补丁,而是**那份锁在缺草稿件时也会被派生出来**。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from repoproof.adoption.intake.upstream_pin import (
    derive_reference_lock,
    normalize_dist_name,
    reference_lock_from_checkout,
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


def _tagged_dynamic_tree(
    project_root: Path,
    *,
    tag: str | None,
    distribution: str = "Pint",
) -> tuple[Path, str]:
    staging = project_root / "staging"
    staging.mkdir(parents=True)
    (staging / "pyproject.toml").write_text(
        f'[project]\nname = "{distribution}"\ndynamic = ["version"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet", str(staging)], check=True)
    subprocess.run(["git", "-C", str(staging), "add", "pyproject.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(staging),
            "-c",
            "user.name=RepoProof Test",
            "-c",
            "user.email=repoproof@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(staging), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if tag is not None:
        subprocess.run(["git", "-C", str(staging), "tag", tag], check=True)
    target = project_root / "upstream-cache" / f"upstream-{commit[:12]}"
    target.parent.mkdir(parents=True)
    staging.replace(target)
    return target, commit


def test_dynamic_version_uses_release_tag_bound_to_frozen_commit(tmp_path: Path):
    _upstream, commit = _tagged_dynamic_tree(tmp_path, tag="0.25.3")

    lock = derive_reference_lock(
        tmp_path,
        distribution="Pint",
        resolved_commit=commit,
        requested_revision="0.25.3",
    )

    assert "Pint==0.25.3" in lock


def test_shallow_fetch_head_tag_is_bound_without_persistent_tag_ref(tmp_path: Path):
    upstream, commit = _tagged_dynamic_tree(tmp_path, tag="0.25.3")
    subprocess.run(
        ["git", "-C", str(upstream), "tag", "--delete", "0.25.3"],
        capture_output=True,
        check=True,
    )
    (upstream / ".git" / "FETCH_HEAD").write_text(
        f"{commit}\t\ttag '0.25.3' of https://github.com/example/pint\n",
        encoding="utf-8",
    )

    lock = derive_reference_lock(
        tmp_path,
        distribution="Pint",
        resolved_commit=commit,
        requested_revision="0.25.3",
    )

    assert "Pint==0.25.3" in lock


def test_distribution_prefixed_release_tag_is_supported_without_keywords(
    tmp_path: Path,
):
    _upstream, commit = _tagged_dynamic_tree(
        tmp_path,
        tag="networkx-3.6.1",
        distribution="networkx",
    )

    lock = derive_reference_lock(
        tmp_path,
        distribution="networkx",
        resolved_commit=commit,
        requested_revision="networkx-3.6.1",
    )

    assert "networkx==3.6.1" in lock


def test_analysis_checkout_can_bootstrap_lock_before_formal_cache_exists(
    tmp_path: Path,
):
    checkout, commit = _tagged_dynamic_tree(
        tmp_path,
        tag="networkx-3.6.1",
        distribution="networkx",
    )
    assert not (tmp_path / "fresh" / "upstream-cache").exists()

    lock = reference_lock_from_checkout(
        checkout,
        distribution="networkx",
        resolved_commit=commit,
        requested_revision="networkx-3.6.1",
    )

    assert "networkx==3.6.1" in lock


def test_intake_persists_bootstrap_lock_into_new_draft_bundle(tmp_path: Path):
    from repoproof.adoption.intake.tool_confirm import write_draft_bundle
    from repoproof.adoption.intake.tool_intake import run_tool_intake

    checkout, _commit = _tagged_dynamic_tree(
        tmp_path,
        tag="networkx-3.6.1",
        distribution="networkx",
    )
    report = run_tool_intake(
        "https://github.com/example/networkx",
        "整理一份关系摘要",
        cache_root=tmp_path / "analysis-cache",
        revision="networkx-3.6.1",
        local_path=checkout,
    )
    bundle = write_draft_bundle(report, tmp_path / "draft")

    assert (bundle / "reference.lock.txt").read_text(encoding="utf-8").endswith(
        "networkx==3.6.1\n"
    )


def test_versionish_revision_without_matching_tag_is_not_trusted(tmp_path: Path):
    _upstream, commit = _tagged_dynamic_tree(tmp_path, tag=None)

    assert derive_reference_lock(
        tmp_path,
        distribution="Pint",
        resolved_commit=commit,
        requested_revision="0.25.3",
    ) == ""


def test_release_tag_for_another_commit_is_not_trusted(tmp_path: Path):
    upstream, first_commit = _tagged_dynamic_tree(tmp_path, tag="0.25.3")
    (upstream / "README.md").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(upstream), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(upstream),
            "-c",
            "user.name=RepoProof Test",
            "-c",
            "user.email=repoproof@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "next",
        ],
        check=True,
    )
    second_commit = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert second_commit != first_commit
    target = tmp_path / "upstream-cache" / f"upstream-{second_commit[:12]}"
    upstream.replace(target)

    assert derive_reference_lock(
        tmp_path,
        distribution="Pint",
        resolved_commit=second_commit,
        requested_revision="0.25.3",
    ) == ""


def test_dynamic_version_uses_pinned_import_literal_without_execution(
    tmp_path: Path,
) -> None:
    up = _tree(tmp_path, '[project]\nname = "x"\ndynamic = ["version"]\n')
    package = up / "src" / "x"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '__version__ = "2.4.1"\nraise RuntimeError("must not execute")\n',
        encoding="utf-8",
    )

    assert upstream_version(up, import_module="x") == "2.4.1"
    lock = derive_reference_lock(
        tmp_path,
        distribution="x",
        resolved_commit=_COMMIT,
        import_module="x",
    )
    assert "x==2.4.1" in lock


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
    import yaml

    from repoproof.adoption.delivery.product_profile import product_delivery_profile
    from repoproof.adoption.intake.intent_contract import (
        install_artifact_protocol,
        install_delivery_intent_from_interface,
        install_semantic_commitments,
        new_intent_contract,
    )
    from repoproof.ui.services import product_jobs

    state = tmp_path / "state"
    draft = state / "drafts" / "d"
    (draft / "examples").mkdir(parents=True)
    output_format, output_contract = product_delivery_profile().contract_for("json")
    document = {
        "_delivery_profile": {"schema_version": 1, "profile_id": "cli_v2"},
        "_intent_contract": new_intent_contract("整理输入并返回 JSON"),
        "tool": {
            "schema_version": 3,
            "name": "demo-tool",
            "summary": summary,
            "interface": {
                "input": {"kind": "file", "format": "TEXT"},
                "output": {
                    "kind": "stdout",
                    "format": output_format,
                    "contract": output_contract.model_dump(mode="json"),
                },
            },
        },
        "capability": {"statement": "", "output_schema": "DemoOut"},
        "source_repo": {
            "url": "https://github.com/example/webcolors",
            "distribution": "webcolors",
            "import_module": "webcolors",
            "resolved_commit": _COMMIT,
            "license": "BSD-3-Clause",
        },
    }
    install_delivery_intent_from_interface(document, profile_id="cli_v2")
    install_semantic_commitments(document, [{
        "commitment_id": "produce-json",
        "public_text": "把一个本地文件整理为确定性的 JSON 结果。",
        "rationale": "保存审核页回归夹具的公开行为。",
    }])
    install_artifact_protocol(document, {
        "schema_version": 1,
        "protocol_id": "json-result-v1",
        "observations": [{
            "observation_id": "json-document",
            "commitment_ids": ["produce-json"],
            "locator": "完整 JSON 根文档",
            "value_encoding": "UTF-8 JSON 文档",
        }],
    })
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
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
        reference_impl="# demo\n", semantic_commitments=["新的能力陈述"])
    assert got.get("ok"), got
    assert "新摘要" in (draft / "draft.yaml").read_text(encoding="utf-8")
