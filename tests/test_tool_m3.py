"""M3 三件的钉死:注册表 / MCP 机械转换 / 单命令旅程编排。

- 注册表是索引不是事实源:漂移如实标注(MISSING/UNVERIFIED),scan
  补录不伪造导出时间;
- MCP server 由 manifest 机械生成:协议三段(initialize/tools/list/
  tools/call)真子进程驱动;未验证工具拒生成;
- pipeline:合成 minilib 世界零网走到彩排门(REHEARSAL_PASS_ONLY),
  编排不吞错 —— confirm 失败原样传导(ConfirmError)。
"""

from __future__ import annotations

import json
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
import yaml

from repoproof.runner.tool_mcp import (
    WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED,
    write_mcp_server,
)
from repoproof.runner.tool_registry import list_tools, register_tool
from repoproof.runner.tool_release import ACTIVE, append_release_decision
from tests.conftest import isolate_protected_dirs

_REPO_PY = sys.executable
_REPO_SITE = sysconfig.get_paths()["purelib"]


def test_analysis_checkout_promotion_preserves_tracked_symlink(tmp_path: Path) -> None:
    from repoproof.runner.tool_pipeline import ensure_pinned_upstream

    analysis = tmp_path / "upstream-cache" / "analysis" / "source"
    analysis.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(analysis)], check=True)
    subprocess.run(
        ["git", "-C", str(analysis), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(analysis), "config", "user.name", "RepoProof Test"],
        check=True,
    )
    (analysis / "LICENSE.txt").write_text("license\n", encoding="utf-8")
    (analysis / "LICENSE").symlink_to("LICENSE.txt")
    subprocess.run(["git", "-C", str(analysis), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(analysis), "commit", "-qm", "fixture"],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(analysis), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    promoted = ensure_pinned_upstream("https://example.invalid/repo", commit, tmp_path)

    assert (promoted / "LICENSE").is_symlink()
    assert (promoted / "LICENSE").readlink() == Path("LICENSE.txt")
    assert not subprocess.run(
        ["git", "-C", str(promoted), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _fake_tool(dest: Path, name: str, *, verified: bool = True) -> Path:
    d = dest / name
    (d / "bin").mkdir(parents=True)
    (d / "evidence").mkdir()
    (d / "bin" / name).write_text(
        "#!/bin/bash\necho \"| ok |\"\n", encoding="utf-8")
    (d / "bin" / name).chmod(0o755)
    (d / "tool.json").write_text(json.dumps({
        "manifest_version": 1, "name": name, "version": "1.0.0",
        "summary": "假工具(测试)",
        "source": {"url": "u", "resolved_commit": "c", "license": "MIT",
                   "distribution": "d"},
        "interface": {"usage": f"{name} <in>",
                      "input": {"kind": "file", "format": "TXT"},
                      "output": {"kind": "stdout", "format": "TXT"},
                      "exit_codes": {"0": "s", "1": "u", "2": "i"}},
        "verification": ({"verdict": "VERIFIED_TOOL_READY", "run_id": "r-1",
                          "contract_sha256": "abc"} if verified else None),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": name,
                "task_id": f"tool-{name}-v1",
                "run_id": "r-1",
                "tool_contract_sha256": "abc",
            }
        ),
        encoding="utf-8",
    )
    return d


# ------------------------------------------------------------------ 注册表

def test_registry_register_list_and_drift(tmp_path):
    d = _fake_tool(tmp_path, "alpha")
    entry = register_tool(tmp_path, d, run_id="r-1", exported_at="2026-08-23T00:00:00Z")
    assert entry["task_id"] == "tool-alpha-v1"
    rows = list_tools(tmp_path)
    assert rows[0]["name"] == "alpha" and rows[0]["status"] == "OK"

    # 漂移:工具目录被删 → MISSING(如实标注,不静默剔除)
    import shutil

    shutil.rmtree(d)
    rows = list_tools(tmp_path)
    assert rows[0]["status"] == "MISSING"


def test_registry_scan_backfills_without_forging_time(tmp_path):
    _fake_tool(tmp_path, "beta")
    _fake_tool(tmp_path, "gamma", verified=False)
    rows = {r["name"]: r for r in list_tools(tmp_path, scan=True)}
    assert rows["beta"]["exported_at"] is None
    assert rows["beta"]["provenance"] == "scan"
    assert rows["beta"]["status"] == "OK"
    assert rows["gamma"]["status"] == "UNVERIFIED"


# ------------------------------------------------------------------ MCP

def test_mcp_refuses_unverified_tool(tmp_path):
    d = _fake_tool(tmp_path, "nover", verified=False)
    with pytest.raises(RuntimeError):
        write_mcp_server(d)


def test_mcp_stably_refuses_workspace_bundle_profile(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "workspace-demo")
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 4
    manifest["delivery_profile_id"] = "workspace_bundle_v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match=WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED):
        write_mcp_server(tool_dir)
    assert not (tool_dir / "mcp_server.py").exists()


def test_mcp_server_protocol_and_call(tmp_path):
    d = _fake_tool(tmp_path, "echoer")
    append_release_decision(
        tmp_path,
        tool="echoer",
        task_id="tool-echoer-v1",
        run_id="r-1",
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="test fresh-input audit passed",
        evidence_sha256="0" * 64,
        decided_at="2026-08-23T00:00:00Z",
        actor="operator",
    )
    server = write_mcp_server(d)
    inp = tmp_path / "in.jsonl"
    probe = tmp_path / "probe.txt"
    probe.write_text("x", encoding="utf-8")
    inp.write_text(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        '{"jsonrpc":"2.0","id":3,"method":"tools/call",'
        f'"params":{{"arguments":{{"input_path":"{probe}"}}}}}}\n'
        '{"jsonrpc":"2.0","id":4,"method":"bogus/xyz"}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(server)],
                       stdin=inp.open(), capture_output=True, text=True,
                       timeout=120)
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    assert len(lines) == 4, r.stdout          # 通知不回;四个带 id 的都回
    by_id = {d2["id"]: d2 for d2 in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "echoer"
    tool = by_id[2]["result"]["tools"][0]
    assert tool["name"] == "echoer" and tool["inputSchema"]["required"] == ["input_path"]
    assert by_id[3]["result"]["content"][0]["text"].strip() == "| ok |"
    assert by_id[3]["result"]["isError"] is False
    assert by_id[4]["error"]["code"] == -32601


# ---------------------------------------- bench 规则准入(tool-* 两项制)

def test_bench_tool_prefix_rule_admission(tmp_path):
    """tool-* 条目免登记,但内部两项制强制:私货照报 stray(#29 兜底)。"""
    from repoproof.harness.host_guard import bench_root_strays

    (tmp_path / "tool-x-v1" / "host").mkdir(parents=True)
    (tmp_path / "tool-x-v1" / "wheelhouse").mkdir()
    assert bench_root_strays(tmp_path) == []
    (tmp_path / "tool-x-v1" / "answers").mkdir()          # 私货
    (tmp_path / "rogue-dir").mkdir()                       # 非 tool 前缀
    assert bench_root_strays(tmp_path) == ["rogue-dir", "tool-x-v1/answers"]


# ------------------------------------------------ pipeline(零网,到彩排门)

_MINILIB = ('MAGIC = "MINI\\n"\n\n\nclass FormatError(ValueError):\n    pass\n\n\n'
            'def rows_to_markdown(text):\n'
            '    if not text.startswith(MAGIC):\n'
            '        raise FormatError("missing MINI header")\n'
            '    rows = [l for l in text[len(MAGIC):].splitlines() if l.strip()]\n'
            '    return "\\n".join(f"| {r} |" for r in rows)\n')

_REFERENCE = ('"""reference:真调 minilib。"""\nfrom pathlib import Path\n\n'
              'import minilib\n\n\nclass UserInputError(ValueError):\n    pass\n\n\n'
              'def extract(input_path: Path) -> str:\n'
              '    try:\n'
              '        text = input_path.read_text(encoding="utf-8")\n'
              '    except UnicodeDecodeError as e:\n'
              '        raise UserInputError(str(e)) from e\n'
              '    try:\n'
              '        return minilib.rows_to_markdown(text)\n'
              '    except minilib.FormatError as e:\n'
              '        raise UserInputError(str(e)) from e\n')

_SEMANTIC_VERIFIER = (
    '"""Independent semantic verifier for the synthetic minilib task."""\n'
    'from pathlib import Path\n\n'
    'import minilib\n\n\n'
    'def verify(input_path: Path, artifact_path: Path) -> dict:\n'
    '    expected = minilib.rows_to_markdown(input_path.read_text(encoding="utf-8"))\n'
    '    actual = artifact_path.read_text(encoding="utf-8")\n'
    '    return {\n'
    '        "ok": actual == expected,\n'
    '        "reason_codes": [] if actual == expected else ["SEMANTIC_MISMATCH"],\n'
    '        "checked_commitment_ids": [\n'
    '            "render-rows",\n'
    '            "reject-invalid-header",\n'
    '        ],\n'
    '    }\n'
)


@pytest.mark.slow
def test_pipeline_runs_to_rehearsal_gate_offline(tmp_path, monkeypatch):
    from repoproof.adoption.intake.intent_contract import (
        confirm_intent_contract,
        install_artifact_protocol,
        install_delivery_intent_from_interface,
        install_semantic_commitments,
    )
    from repoproof.adoption.intake.tool_confirm import (
        ConfirmError,
        confirm_tool_draft,
        write_draft_bundle,
    )
    from repoproof.adoption.intake.tool_intake import run_tool_intake
    from repoproof.runner.tool_pipeline import tool_build

    # 只按 DEFAULT_PROTECTED 不够:结构性发现会把真兄弟仓拉回来
    # (2026-08-26 上线后隔离一度悄悄失效)。走会自检的共用夹具。
    isolate_protected_dirs(monkeypatch)

    project = tmp_path / "proj"
    # 合成 minilib 上游(git)+ 直接落 pinned 位(ensure 走"已存在"分支,零网)
    up_src = tmp_path / "up"
    (up_src / "minilib").mkdir(parents=True)
    (up_src / "minilib" / "__init__.py").write_text(_MINILIB, encoding="utf-8")
    (up_src / "pyproject.toml").write_text(
        '[project]\nname = "minilib"\nversion = "0.1.0"\n'
        'requires-python = ">=3.10"\ndependencies = []\n'
        '[build-system]\nrequires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (up_src / "LICENSE").write_text("MIT License", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "pin"]):
        subprocess.run(["git", "-C", str(up_src), *args], check=True,
                       capture_output=True)
    head = subprocess.run(["git", "-C", str(up_src), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    pinned = project / "upstream-cache" / f"upstream-{head[:12]}"
    pinned.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(up_src, pinned)

    # intake → draft 束 → 程序化人补(minilib 语义)
    rep = run_tool_intake("file://minilib", "MINI 文本转 Markdown",
                          cache_root=tmp_path / "cache", local_path=pinned)
    dest = write_draft_bundle(rep, tmp_path / "draft")
    doc = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    doc["source_repo"]["url"] = "file://minilib"
    doc["source_repo"]["resolved_commit"] = head
    doc["tool"]["summary"] = "MINI→MD"
    doc["tool"]["interface"]["input"]["format"] = "TXT"
    doc["tool"]["interface"]["output"]["format"] = "Markdown"
    doc["tool"]["interface"]["output"]["contract"] = {
        "media_type": "text/markdown",
        "root_type": "text",
        "required": {},
        "validation_profile": "markdown_document_v1",
    }
    doc["capability"]["output_schema"] = "MdRows"
    install_delivery_intent_from_interface(doc, profile_id="cli_v2")
    install_semantic_commitments(doc, [
        {
            "commitment_id": "render-rows",
            "public_text": "使用固定版本上游把 MINI 文本的非空行按原顺序转为 Markdown 行表。",
            "rationale": "用户需要的主能力。",
        },
        {
            "commitment_id": "reject-invalid-header",
            "public_text": "缺少 MINI 头的输入不属于有效域，应返回用户输入错误。",
            "rationale": "固定上游对无效格式有明确边界。",
        },
    ])
    install_artifact_protocol(doc, {
        "schema_version": 1,
        "protocol_id": "mini-markdown-v1",
        "observations": [
            {
                "observation_id": "rendered-rows",
                "commitment_ids": ["render-rows"],
                "locator": "Markdown table body rows in document order",
                "value_encoding": "UTF-8 Markdown table rows",
            },
            {
                "observation_id": "invalid-header-result",
                "commitment_ids": ["reject-invalid-header"],
                "locator": "process exit status and stderr category",
                "value_encoding": "user-input error",
            },
        ],
    })
    confirm_intent_contract(doc, confirmed_at="2026-08-30T00:00:00Z")
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for n, txt in (("a", "MINI\nalpha"), ("b", "MINI\nbeta"), ("c", "MINI\ngamma")):
        (dest / "examples" / f"{n}.txt").write_text(txt, encoding="utf-8")
    (dest / "examples.yaml").write_text(yaml.safe_dump({"examples": [
        {"input": "--help", "expected": "contains:usage"},
        {"input_file": "a.txt", "expected": "contains:| alpha |"},
        {"input_file": "b.txt", "expected": "contains:| beta |"},
        {"input_file": "c.txt", "expected": "contains:| gamma |"},
    ]}, allow_unicode=True), encoding="utf-8")
    (dest / "reference_impl.py").write_text(_REFERENCE, encoding="utf-8")
    (dest / "semantic_verifier.py").write_text(
        _SEMANTIC_VERIFIER, encoding="utf-8"
    )

    shim = (
        "import os, pathlib\n"
        "host = pathlib.Path(os.getcwd())\n"
        "b = host/'.venv'/'bin'; b.mkdir(parents=True, exist_ok=True)\n"
        "p = b/'python'\n"
        "p.write_text('#!/bin/bash\\n'\n"
        f"    'export PYTHONPATH=\"'+str(host/'src')+':{pinned}:{_REPO_SITE}:'"
        "+'${PYTHONPATH:-}\"\\n'\n"
        f"    'exec \"{_REPO_PY}\" \"$@\"\\n')\n"
        "p.chmod(0o755)\nprint('shim ready')\n")

    out = tool_build(
        dest, project, bench_root=tmp_path / "bench",
        dest_root=tmp_path / "tools", run_real=False,
        setup_commands=[[_REPO_PY, "-c", shim]],
        wheelhouse_cmd=["true"])
    assert out["verdict"] == "REHEARSAL_PASS_ONLY", out["stages"]
    assert out["stages"]["rehearsal"]["verdict"] == "PASS_ADAPTED"
    assert out["stages"]["confirm"]["held"] == 1
    # conformance:minilib 无 tests 目录 → 空选取如实
    assert out["stages"]["conformance_selected"] == []
    # draft 束已归档(移出 H9-a 扫描面),原位不再存在
    archived = Path(out["stages"]["draft_archived"])
    assert archived.is_dir() and (archived / "draft.yaml").is_file()
    assert not dest.exists()
    shutil.copytree(archived, dest)      # 拷回供后续负例断言使用

    # 重复 build 不撞车 —— 装配器从全部不可变谱系锚点取最大版本 + 1。
    # 即使存在孤立 v2 物化目录也绝不复用或填洞,而是冻结为 v3。
    v2_dir = project / "tool_tasks" / "tool-minilib-tool-v2"
    v2_dir.mkdir(parents=True)
    out_v3 = tool_build(
        dest, project, bench_root=tmp_path / "bench",
        dest_root=tmp_path / "tools", run_real=False,
        setup_commands=[[_REPO_PY, "-c", shim]],
        wheelhouse_cmd=["true"])
    assert out_v3["task_id"] == "tool-minilib-tool-v3"
    assert out_v3["verdict"] == "REHEARSAL_PASS_ONLY"
    archived_v3 = Path(out_v3["stages"]["draft_archived"])
    shutil.copytree(archived_v3, dest)
    # 编排不吞错:confirm 失败原样传导
    (dest / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    with pytest.raises(ConfirmError):
        confirm_tool_draft(dest, project)

# ---------------- 备轮必须含上游(2026-08-28 webcolors 三发白跑的根因) ----------------

def _pinned_tree(tmp_path: Path, *, version: str | None) -> Path:
    up = tmp_path / "upstream-e6392ba6eeba"
    up.mkdir(parents=True)
    body = '[project]\nname = "webcolors"\n'
    if version:
        body += f'version = "{version}"\n'
    (up / "pyproject.toml").write_text(body, encoding="utf-8")
    return up


def test_missing_lock_derives_upstream_pin_from_the_pinned_tree(tmp_path: Path):
    """锁文件缺席时,从**钉版树自己**声明的版本派生上游 pin。

    实录:`reference.lock.txt` 在人务清单里写着"(可选)",而它一旦缺席,
    `_reference_pins` 静默返回空 → wheelhouse 只装 pytest 那套 → 会话里
    没有上游 → 每条能力测试炸 ModuleNotFoundError,再被包装成
    DEPENDENCY_ERROR,在三轮修复之后才浮出来。"可选"是假的:不写就必崩。
    """
    from repoproof.runner.tool_pipeline import resolve_upstream_pins

    pins = resolve_upstream_pins(
        tmp_path, "tool-webcolors-tool-v3",
        distribution="webcolors", upstream_dir=_pinned_tree(tmp_path, version="25.10.0"))
    assert pins == ["webcolors==25.10.0"]


def test_existing_lock_wins_and_is_not_duplicated(tmp_path: Path):
    """锁文件已写了上游就以它为准 —— 派生只补缺,不覆盖人的选择。"""
    from repoproof.runner.tool_pipeline import resolve_upstream_pins

    lock = tmp_path / "controls" / "t1" / "reference"
    lock.mkdir(parents=True)
    (lock / "requirements.lock.txt").write_text(
        "# 人写的\nwebcolors==24.11.1\n", encoding="utf-8")

    pins = resolve_upstream_pins(
        tmp_path, "t1", distribution="webcolors",
        upstream_dir=_pinned_tree(tmp_path, version="25.10.0"))
    assert pins == ["webcolors==24.11.1"]        # 不被派生版本挤掉,也不重复


def test_underivable_pin_refuses_loudly_instead_of_building_a_doomed_wheelhouse(tmp_path: Path):
    """**负控**:既没有锁、也读不出版本 → 当场拒发。

    绝不建一个"注定装不上上游"的 wheelhouse 然后让它在三轮之后炸 ——
    静默降级正是这个 bug 的全部危害所在。
    """
    from repoproof.runner.tool_pipeline import PipelineError, resolve_upstream_pins

    with pytest.raises(PipelineError, match="备轮缺上游"):
        resolve_upstream_pins(
            tmp_path, "t2", distribution="webcolors",
            upstream_dir=_pinned_tree(tmp_path, version=None))


# ------------- 彩排之后的下半程(2026-08-28:用户切走再回来,草稿没了) -------------

def test_rehearsed_tasks_lists_frozen_but_unexported(tmp_path: Path):
    """彩排过、还没导出的任务要能被列出来 —— 否则彩排通过就无路可走。

    实录:`tool_build` 在彩排**之前**就把草稿 `shutil.move` 进归档区
    (冻结即消耗,本身是对的:题面已冻结,草稿不该再被编辑)。但 UI 只有
    "从草稿构建"一个入口,于是用户彩排通过、切去看运行记录、回来一看
    "草稿目录不存在" —— 只能重建草稿再冻一版(用户手上 v1..v5 就是这么
    来的)。缺的不是纪律,是**流程的下半程**。
    """
    from repoproof.runner.tool_pipeline import rehearsed_tasks

    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "tool-demo-v1.yaml").write_text("kind: x\n", encoding="utf-8")
    (tmp_path / "contracts" / "tool-done-v1.yaml").write_text("kind: x\n", encoding="utf-8")
    ledger = tmp_path / "benchmarks" / "v2"
    ledger.mkdir(parents=True)
    (ledger / "runs.jsonl").write_text("\n".join([
        json.dumps({"task_id": "tool-demo-v1", "run_id": "r1",
                    "model": "fake-scripted:positive", "verdict": "PASS_ADAPTED"}),
        json.dumps({"task_id": "tool-done-v1", "run_id": "r2",
                    "model": "fake-scripted:positive", "verdict": "PASS_ADAPTED"}),
        json.dumps({"task_id": "tool-done-v1", "run_id": "r3",
                    "model": "gpt-5.6-terra", "verdict": "PASS_ADAPTED"}),
    ]) + "\n", encoding="utf-8")

    got = rehearsed_tasks(tmp_path)
    ids = [r["task_id"] for r in got]
    assert ids == ["tool-demo-v1"]            # 已真发过的不再列
    assert got[0]["verdict"] == "PASS_ADAPTED"


def test_resume_refuses_when_the_task_was_never_frozen(tmp_path: Path):
    """**负控**:没有冻结合同就没有可续跑的东西 —— 如实拒绝,不臆造。"""
    from repoproof.runner.tool_pipeline import (
        PipelineError,
        tool_build_real_from_frozen,
    )

    with pytest.raises(PipelineError, match="找不到已冻结的任务合同"):
        tool_build_real_from_frozen("tool-nope-v1", tmp_path,
                                    dest_root=tmp_path / "tools")


def test_resume_passes_the_host_contract_not_the_tool_contract(tmp_path: Path, monkeypatch):
    """**续跑必须传物化出来的宿主合同** —— 传错那份会炸得像"题面缺字段"。

    2026-08-28 实测:第一版续跑把 `contracts/<task>.yaml`(工具合同,
    TaskContract)喂给了 run_host_guided_cli(它要 HostContract),于是
    抛一串 pydantic `Field required: budgets.max_rounds /
    acceptance.hidden_oracle_command` —— 看起来像题面写漏了字段,其实是
    拿错了文件。两份合同同名不同 schema,这类错必须被钉住。
    """
    from repoproof.runner import tool_pipeline

    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "tool-demo-v1.yaml").write_text(
        "kind: tool\ntool: {name: demo}\n", encoding="utf-8"
    )
    host = tmp_path / "tool_tasks" / "tool-demo-v1"
    host.mkdir(parents=True)
    (host / "contract.yaml").write_text("kind: host_integrated\n", encoding="utf-8")

    seen: dict = {}

    def _spy(contract, project_root, **kwargs):
        seen["contract"] = Path(contract)
        return {"blocked": True, "reason": "spy"}

    monkeypatch.setattr(tool_pipeline, "run_host_guided_cli", _spy, raising=False)
    monkeypatch.setattr("repoproof.runner.host_guided.run_host_guided_cli", _spy)
    from repoproof.runner.product_preflight import ProductPreflightResult
    monkeypatch.setattr(
        "repoproof.runner.product_preflight.run_product_preflight",
        lambda **_kwargs: ProductPreflightResult(ok=True),
    )

    tool_pipeline.tool_build_real_from_frozen(
        "tool-demo-v1", tmp_path, dest_root=tmp_path / "tools")

    assert seen["contract"] == host / "contract.yaml", seen
    assert seen["contract"].name == "contract.yaml"          # 不是 contracts/*.yaml


def test_frozen_resume_rejects_legacy_mcp_before_real_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upgrade blocker is a zero-model preflight, not a post-Agent surprise."""

    from repoproof.runner import tool_pipeline
    from repoproof.runner.tool_export import ToolExportError

    task_id = "tool-demo-v2"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / f"{task_id}.yaml").write_text(
        "kind: tool\ntool: {name: demo}\n", encoding="utf-8"
    )
    host = tmp_path / "tool_tasks" / task_id
    host.mkdir(parents=True)
    (host / "contract.yaml").write_text(
        "host: {wheelhouse_path: /unused}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        tool_pipeline,
        "preflight_tool_install",
        lambda *_args: (_ for _ in ()).throw(
            ToolExportError("LEGACY_MCP_MUST_BE_DETACHED")
        ),
    )
    monkeypatch.setattr(
        "repoproof.runner.host_guided.run_host_guided_cli",
        lambda *_args, **_kwargs: pytest.fail("real Agent must not run"),
    )

    with pytest.raises(tool_pipeline.PipelineError) as caught:
        tool_pipeline.tool_build_real_from_frozen(
            task_id, tmp_path, dest_root=tmp_path / "tools"
        )

    assert caught.value.reason_code == "LEGACY_MCP_MUST_BE_DETACHED"
    assert (
        caught.value.partial_result["stages"]["install_preflight"]["ok"]
        is False
    )


def test_frozen_resume_can_repeat_rehearsal_without_real_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_pipeline
    from repoproof.runner.product_preflight import ProductPreflightResult

    task_id = "tool-demo-v1"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / f"{task_id}.yaml").write_text(
        "kind: tool\n", encoding="utf-8"
    )
    host = tmp_path / "tool_tasks" / task_id
    host.mkdir(parents=True)
    (host / "contract.yaml").write_text(
        "host: {wheelhouse_path: /unused}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "repoproof.runner.product_preflight.run_product_preflight",
        lambda **_kwargs: ProductPreflightResult(ok=True),
    )
    calls: list[dict] = []

    def _fake(_contract, _project_root, **kwargs):
        calls.append(kwargs)
        return {
            "blocked": False,
            "report": {
                "verdict": "PASS_ADAPTED",
                "run_id": "fake-rehearsal",
                "gate_reasons": [],
            },
        }

    monkeypatch.setattr(
        "repoproof.runner.host_guided.run_host_guided_cli", _fake
    )
    result = tool_pipeline.tool_build_real_from_frozen(
        task_id,
        tmp_path,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
    )

    assert result["verdict"] == "REHEARSAL_PASS_ONLY"
    assert calls == [{"fake": "positive", "batch": "EXPLORATORY_UNPREREGISTERED"}]


def test_frozen_rehearsal_environment_failure_is_structured_and_zero_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An early Harness setup exception must still produce one Product stop."""

    from repoproof.runner import tool_pipeline
    from repoproof.runner.host_guided import HostRunError
    from repoproof.runner.product_preflight import ProductPreflightResult

    task_id = "tool-anonymous-workspace-v1"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / f"{task_id}.yaml").write_text(
        "kind: tool\n", encoding="utf-8"
    )
    host = tmp_path / "tool_tasks" / task_id
    host.mkdir(parents=True)
    (host / "contract.yaml").write_text(
        "host: {wheelhouse_path: /unused}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "repoproof.runner.product_preflight.run_product_preflight",
        lambda **_kwargs: ProductPreflightResult(ok=True),
    )
    monkeypatch.setattr(
        "repoproof.runner.host_guided.run_host_guided_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HostRunError("offline verifier dependency missing")
        ),
    )

    with pytest.raises(tool_pipeline.PipelineError) as caught:
        tool_pipeline.tool_build_real_from_frozen(
            task_id,
            tmp_path,
            dest_root=tmp_path / "tools",
            rehearsal_only=True,
        )

    assert caught.value.reason_code == "HARNESS_EXECUTION_ENVIRONMENT_FAILED"
    assert caught.value.partial_result["verdict"] == "BLOCKED"
    assert "没有调用 Agent" in str(caught.value.recommended_action)


def test_resume_refuses_when_task_was_never_materialised(tmp_path: Path):
    """**负控**:只有工具合同、没有物化产物 → 如实拒绝并说清原因。"""
    from repoproof.runner.tool_pipeline import (
        PipelineError,
        tool_build_real_from_frozen,
    )

    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "tool-demo-v1.yaml").write_text("kind: tool\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="物化的宿主合同"):
        tool_build_real_from_frozen("tool-demo-v1", tmp_path,
                                    dest_root=tmp_path / "tools")


def test_frozen_pre_materialization_stop_resumes_same_task_without_refreeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_pipeline

    task_id = "tool-demo-v1"
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / f"{task_id}.yaml").write_text("task_id: tool-demo-v1\n")
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "draft.yaml").write_text("tool: {name: demo}\n")
    captured: dict = {}

    def fake_build(draft_dir, project_root, **kwargs):
        captured.update({
            "draft_dir": draft_dir,
            "project_root": project_root,
            **kwargs,
        })
        return {"task_id": task_id, "verdict": "REHEARSAL_PASS_ONLY"}

    monkeypatch.setattr(tool_pipeline, "tool_build", fake_build)
    result = tool_pipeline.tool_build_real_from_frozen(
        task_id,
        tmp_path,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
        draft_dir=draft,
        bench_root=tmp_path / "bench",
    )

    assert result["task_id"] == task_id
    assert captured["resume_task_id"] == task_id
    assert captured["run_real"] is False
    assert captured["draft_dir"] == draft
