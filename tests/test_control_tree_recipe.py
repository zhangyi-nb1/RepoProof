"""控制组装配配方的钉死(LESSONS #41 的后半段)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- C1 配方完整:装配结果 = 钉版上游 + 任务包 `fixtures/` + 任务包
  `public_tests/` + `controls/<name>/*.py` + `rag_api.py` 末尾的挂载。
  反例:2026-08-13 之前配方**只存在于 7 棵手搓树里**,仓里的 `controls/`
  只有 6 个 `research_jobs.py`,少了那 3 行挂载 —— 照仓里的东西装不出
  能跑的控制组,于是那 7 棵树谁也不敢删,一直占着 H9-a 的拒开条件。
- C2 只带正文不带包袱:`.venv` / `.git` / `__pycache__` 不进装配结果。
  反例:7 棵手搓树 618MB 里 ~610MB 是 7 份 `.venv`;`.git` 更糟 —— 会把
  上游完整历史复制进一棵**agent 可能够得着**的树。
- C3 挂载恰好一次:`mount_research_api(app)` 出现 0 次装不起来,出现 2 次
  是重复挂载。上游若已自带挂载,不得再追加。
- C4 默认即拆:不给 `--keep` 就必须删干净。反例:手搓树的默认是"留着",
  于是每验证一次五物就多 7 棵残留 —— 残留是默认行为的产物,不是疏忽。

判据只管装配器本身;控制组各自的**语义**(nc1 真的没接 ODR 等)由五物验证
执法,不在这里。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(script: str):
    """按**文件路径**加载 —— 红绿/变异闸门用 `PYTHONPATH=<树>/src` 隔离运行,
    包导入在那里找不到 scripts/;这也保证考的是树里那份,不是工作区那份。"""
    spec = importlib.util.spec_from_file_location(script[:-3], REPO / "scripts" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mini_upstream(root, rag_body: str = "app = object()\n"):
    """一棵最小合成上游:含要保留的正文、要被排除的 .venv/.git/__pycache__。"""
    up = root / "up"
    (up / "sub").mkdir(parents=True)
    (up / "rag_api.py").write_text(rag_body)
    (up / "sub" / "mod.py").write_text("VALUE = 1\n")
    (up / ".git").mkdir()
    (up / ".git" / "config").write_text("[core]\n")
    (up / ".venv" / "lib").mkdir(parents=True)
    (up / ".venv" / "lib" / "big.py").write_text("x" * 4096)
    (up / "__pycache__").mkdir()
    (up / "__pycache__" / "stale.pyc").write_bytes(b"\x00")
    return up


def _mini_task(root, control_body: str = "def mount_research_api(app):\n    return app\n"):
    task = root / "task"
    (task / "controls" / "nc1_no_odr").mkdir(parents=True)
    (task / "controls" / "nc1_no_odr" / "research_jobs.py").write_text(control_body)
    (task / "fixtures").mkdir()
    (task / "fixtures" / "fake_llm_server.py").write_text("SERVER = 1\n")
    (task / "public_tests").mkdir()
    (task / "public_tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    return task


def test_recipe_materializes_all_four_sources(tmp_path):
    """C1:四个来源一个都不能少 —— 少了挂载就装不出能跑的控制组。"""
    build = _load("build_control_tree.py").build

    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path)
    dest = build(task, "nc1_no_odr", tmp_path / "out", up)

    assert (dest / "sub" / "mod.py").read_text() == "VALUE = 1\n", "上游正文缺失"
    assert (dest / "fixtures" / "fake_llm_server.py").is_file(), "任务包 fixtures/ 缺失"
    assert (dest / "public_tests" / "test_x.py").is_file(), "任务包 public_tests/ 缺失"
    assert (dest / "research_jobs.py").is_file(), "控制组正文缺失"
    assert "mount_research_api(app)" in (dest / "rag_api.py").read_text(), "挂载缺失"


def test_control_body_is_byte_identical_to_the_repo_original(tmp_path):
    """C1:落地的控制组必须与 controls/ 下的原件逐字节相同,不是"差不多"。"""
    build = _load("build_control_tree.py").build

    body = "# nc1: 故意不接 ODR\ndef mount_research_api(app):\n    return app\n"
    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path, control_body=body)
    dest = build(task, "nc1_no_odr", tmp_path / "out", up)

    src = task / "controls" / "nc1_no_odr" / "research_jobs.py"
    assert (dest / "research_jobs.py").read_bytes() == src.read_bytes()


def test_venv_and_git_and_pycache_are_excluded(tmp_path):
    """C2:610MB 的 .venv 和上游完整历史都不该进这棵树。"""
    build = _load("build_control_tree.py").build

    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path)
    dest = build(task, "nc1_no_odr", tmp_path / "out", up)

    assert not (dest / ".venv").exists(), ".venv 被复制进来了"
    assert not (dest / ".git").exists(), ".git 被复制进来了(上游历史泄进可达树)"
    assert not (dest / "__pycache__").exists(), "__pycache__ 被复制进来了"


def test_mount_is_appended_exactly_once(tmp_path):
    """C3:恰好一次。"""
    build = _load("build_control_tree.py").build

    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path)
    dest = build(task, "nc1_no_odr", tmp_path / "out", up)

    assert (dest / "rag_api.py").read_text().count("mount_research_api(app)") == 1


def test_mount_not_duplicated_when_upstream_already_mounts(tmp_path):
    """C3:上游已自带挂载时不得再追加 —— 重复挂载是另一种装错。"""
    build = _load("build_control_tree.py").build

    up = _mini_upstream(tmp_path, rag_body="app = object()\nmount_research_api(app)\n")
    task = _mini_task(tmp_path)
    dest = build(task, "nc1_no_odr", tmp_path / "out", up)

    assert (dest / "rag_api.py").read_text().count("mount_research_api(app)") == 1


def test_selfcheck_catches_a_botched_assembly(tmp_path):
    """C1/C3:自检要真能报错 —— 装错了当场知道,不是等五物验证出结论才发现。"""
    verify = _load("build_control_tree.py").verify

    dest = tmp_path / "dest"
    dest.mkdir()
    src_control = tmp_path / "ctl"
    src_control.mkdir()
    (src_control / "research_jobs.py").write_text("REAL = 1\n")
    (dest / "research_jobs.py").write_text("TAMPERED = 1\n")
    (dest / "rag_api.py").write_text("mount_research_api(app)\n")

    with pytest.raises(SystemExit):
        verify(dest, src_control)


def test_existing_dest_is_refused_not_overwritten(tmp_path):
    """C4 的另一面:不能默默盖掉别人的目录。"""
    build = _load("build_control_tree.py").build

    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(SystemExit):
        build(task, "nc1_no_odr", dest, up)


def test_default_is_teardown_and_keep_is_opt_in(tmp_path):
    """C4:残留必须是显式选择的结果,不能是默认行为。"""
    main = _load("build_control_tree.py").main

    up, task = _mini_upstream(tmp_path), _mini_task(tmp_path)
    argv = ["--task", str(task), "--control", "nc1_no_odr",
            "--upstream", str(up), "--dest", str(tmp_path / "gone")]

    assert main(argv) == 0
    assert not (tmp_path / "gone").exists(), "默认没拆干净 —— 残留会拒开下一发真实运行"

    kept = tmp_path / "kept"
    assert main(["--task", str(task), "--control", "nc1_no_odr",
                 "--upstream", str(up), "--dest", str(kept), "--keep"]) == 0
    assert kept.is_dir(), "--keep 没留住"
