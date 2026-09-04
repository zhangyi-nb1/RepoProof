"""钉版源码树顶不顶得住发行版(incident-pinned-source-checkout-shadows-built-distribution-*)。

密封运行把钉版源码检出放进 PYTHONPATH,它先于装好的发行版。多数仓库两者一致,遮蔽无害;
但有些仓库的运行期数据是**构建时生成**的,git 树里只留一个占位目录。这时导入照样成功,真
用到那部分能力才炸——而且任何参考实现都改不动它。

判据必须能分开三种真实形态(数字取自本批实测):
  * 整包缺失:发行版 1112 个运行期文件,源码树 29 个,缺 1084(97.5%)——包等于不在;
  * 局部缺失:发行版 168、源码树 224,缺 32 个编译产物,其源文件都在——照样能用;
  * 边角缺失:缺 1 个构建期生成的版本号文件——照样能用。

不变量:
  I1 多数运行期文件缺失 = 源码树顶不住,判 PACKAGE_LARGELY_ABSENT;
  I2 少数缺失只如实报告(PARTIAL),不判死——本批有两个这样的仓库最终跑通了;
  I3 一个不缺 = COMPLETE;
  I4 比不了(没有发行版或找不到源码包)就不下结论,绝不默认判死。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from repoproof.adoption.intake.upstream_conformance import pinned_source_tree_shadowing


def _release(tmp_path: Path, distribution: str, members: dict[str, bytes]) -> Path:
    house = tmp_path / "wheelhouse"
    house.mkdir(exist_ok=True)
    wheel = house / f"{distribution}-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
        archive.writestr(f"{distribution}-1.0.0.dist-info/METADATA", b"Name: x\n")
    return house


def _checkout(tmp_path: Path, package: str, files: dict[str, bytes]) -> Path:
    root = tmp_path / "upstream"
    for name, payload in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


def test_a_package_whose_data_is_generated_at_build_time_is_unusable(tmp_path: Path) -> None:
    released = {"pkg/__init__.py": b"x", "pkg/core.py": b"x"}
    released.update({f"pkg/locale-data/{i}.dat": b"d" for i in range(200)})
    house = _release(tmp_path, "pkg", released)
    root = _checkout(
        tmp_path,
        "pkg",
        {"pkg/__init__.py": b"x", "pkg/core.py": b"x", "pkg/locale-data/.gitignore": b"*.dat\n"},
    )
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["usable"] is False
    assert verdict["severity"] == "PACKAGE_LARGELY_ABSENT"
    assert verdict["missing_count"] == 200
    assert verdict["missing_sample"], "要说出缺了哪些文件"
    assert "pkg" in verdict["remediation"] and verdict["remediation"].strip()


def test_a_few_compiled_artifacts_are_reported_but_not_fatal(tmp_path: Path) -> None:
    # Proportions taken from the real repository: 168 released runtime files,
    # 32 of them compiled translations whose .po sources are all present.
    modules = {f"pkg/m{i}.py": b"x" for i in range(136)}
    released = {"pkg/__init__.py": b"x", **modules}
    released.update({f"pkg/locales/{i}/messages.mo": b"m" for i in range(31)})
    house = _release(tmp_path, "pkg", released)
    files = {
        "pkg/__init__.py": b"x",
        **modules,
        **{f"pkg/locales/{i}/messages.po": b"p" for i in range(31)},
    }
    root = _checkout(tmp_path, "pkg", files)
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["usable"] is True, "少数缺失不判死:本批有两个这样的仓库跑通了"
    assert verdict["severity"] == "PARTIAL"
    assert verdict["missing_count"] == 31


def test_one_generated_version_file_is_not_fatal(tmp_path: Path) -> None:
    released = {"pkg/__init__.py": b"x", "pkg/_version.py": b"v", **{f"pkg/m{i}.py": b"x" for i in range(30)}}
    house = _release(tmp_path, "pkg", released)
    root = _checkout(
        tmp_path, "pkg", {"pkg/__init__.py": b"x", **{f"pkg/m{i}.py": b"x" for i in range(30)}}
    )
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["usable"] is True and verdict["severity"] == "PARTIAL"


def test_a_complete_checkout_is_complete(tmp_path: Path) -> None:
    members = {"pkg/__init__.py": b"x", "pkg/core.py": b"x"}
    house = _release(tmp_path, "pkg", members)
    root = _checkout(tmp_path, "pkg", members)
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["usable"] is True and verdict["severity"] == "COMPLETE"
    assert verdict["missing_count"] == 0


def test_type_stubs_are_not_runtime_files(tmp_path: Path) -> None:
    house = _release(
        tmp_path, "pkg", {"pkg/__init__.py": b"x", "pkg/core.pyi": b"x", "pkg/py.typed": b""}
    )
    root = _checkout(tmp_path, "pkg", {"pkg/__init__.py": b"x"})
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["severity"] == "COMPLETE"


def test_nothing_to_compare_never_condemns(tmp_path: Path) -> None:
    house = tmp_path / "empty"
    house.mkdir()
    root = _checkout(tmp_path, "pkg", {"pkg/__init__.py": b"x"})
    verdict = pinned_source_tree_shadowing(
        upstream_dir=root, wheelhouse=house, distribution="pkg", import_module="pkg"
    )
    assert verdict["usable"] is True and verdict["checked"] is False


def test_the_gate_stops_the_journey_before_any_repair(monkeypatch, tmp_path: Path) -> None:
    """一次模型修复都不花:首轮失败 → 供给判定 → 终态。"""

    from repoproof.adoption.intake.draft_selfcheck import DraftSelfCheckRoundV1
    from repoproof.ui.services import product_jobs

    unusable = {
        "usable": False,
        "checked": True,
        "severity": "PACKAGE_LARGELY_ABSENT",
        "missing_count": 1084,
        "remediation": "改钉已构建的发行版,或换一个用不到该能力的题目。",
    }
    repairs: list[str] = []
    monkeypatch.setattr(
        product_jobs,
        "_self_check_round",
        lambda *_a, **kw: DraftSelfCheckRoundV1(
            round=kw.get("round_index", 1),
            check_ok=False,
            reason_codes=("WORKSPACE_REFERENCE_EXECUTION_FAILED",),
            diagnostics=("RuntimeError",),
        ),
    )
    monkeypatch.setattr(
        product_jobs, "_apply_draft_control_repair", lambda *a, **k: repairs.append("called")
    )
    monkeypatch.setattr(product_jobs, "_pinned_upstream_supply_verdict", lambda *_a, **_k: unusable)
    monkeypatch.setattr(product_jobs, "_core_draft_readiness", lambda *_a, **_k: _ready())
    monkeypatch.setattr(product_jobs, "_validated_draft_dir", lambda *a, **k: (tmp_path, ""))
    (tmp_path / "draft.yaml").write_text(
        "tool:\n  delivery_profile_id: workspace_bundle_v1\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "repoproof.adoption.intake.draft_selfcheck.is_workspace_draft", lambda _d: True
    )

    result = product_jobs.run_draft_self_check(tmp_path, repair=True, drafter=object())

    assert result["status"] == "UNSUPPORTED_PINNED_UPSTREAM"
    assert result["final_reason_codes"] == ["UNSUPPORTED_PINNED_UPSTREAM"]
    assert "改钉已构建的发行版" in result["recommended_action"]
    assert repairs == [], "供给侧判死不该花掉任何一次模型修复"


def test_the_operator_can_override_the_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPOPROOF_ALLOW_SHADOWED_UPSTREAM", "1")
    assert product_jobs_override_is_on()


def product_jobs_override_is_on() -> bool:
    from repoproof.ui.services import product_jobs

    return product_jobs._shadowed_upstream_override()


def _ready():
    from types import SimpleNamespace

    return SimpleNamespace(
        compatible=True, current=True, ready=False, ready_to_confirm=True,
        reason_codes=[], recommended_action="", model_dump=lambda mode: {},
    )
