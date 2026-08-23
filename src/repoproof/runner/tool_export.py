"""Verified Local Tool 导出(M1 · TOOL_PACKAGE_LAYOUT §一/§二/§五)。

把一发 **通过 gate 的** LOCAL-TOOL run 物化成用户可用的工具包:
    <dest_root>/<tool.name>/
        …骨架 + agent 补丁(= 冻结的 adaptation.patch 重放到骨架副本)
        tool.json          verification 键由此处填充(此前必须为 null)
        evidence/          report / adaptation_manifest / verification/*
                           / provenance(EXPORT_ONLY 纪律:held-out 与
                           oracle 永不进包)

纪律:
  - 只认 gate 结论:report.json 的 verdict ∈ {PASS_ADAPTED, PASS_DIRECT},
    其余一律拒导出 —— FAIL 也交付证据包,但那走 run_dir,不落 ~/tools;
  - 交付树 = 骨架 + patch 确定性重建(与 clean replay 同构),不从会话
    工作树拷贝 —— 结论出自 patch,交付也必须出自 patch;
  - agent 写的 tool.json verification 必须是 null(越权声明在此拦截)。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from repoproof.domain.models import TaskContract

_PASS = {"PASS_ADAPTED", "PASS_DIRECT"}


class ToolExportError(RuntimeError):
    pass


def export_verified_tool(
    run_dir: Path,
    *,
    host_contract_path: Path,
    tool_contract_path: Path,
    dest_root: Path,
) -> Path:
    """→ 导出后的工具包根路径。目标已存在则拒绝(不静默覆盖)。"""
    run_dir = Path(run_dir)
    report_p = run_dir / "report.json"
    if not report_p.is_file():
        raise ToolExportError(f"run 目录缺 report.json:{run_dir}")
    report = json.loads(report_p.read_text(encoding="utf-8"))
    verdict = report.get("verdict")
    if verdict not in _PASS:
        raise ToolExportError(
            f"verdict={verdict!r} 不可导出(只认 gate 的 PASS_*;"
            "FAIL 的证据留在 run 目录,不落用户工具区)")

    tc, tc_digest = TaskContract.load_frozen(tool_contract_path, require_sidecar=True)
    if tc.task_family != "LOCAL-TOOL" or tc.tool is None:
        raise ToolExportError(f"{tc.task_id}: 不是 LOCAL-TOOL 契约")
    if report.get("task_id") != tc.task_id:
        raise ToolExportError(
            f"run 属 {report.get('task_id')!r},契约是 {tc.task_id!r} —— 不许错配")

    import yaml
    host_doc = yaml.safe_load(Path(host_contract_path).read_text(encoding="utf-8"))
    host_copy = Path(host_doc["host"]["copy_path"])
    if not host_copy.is_dir():
        raise ToolExportError(f"骨架副本不存在:{host_copy}")

    dest = Path(dest_root) / tc.tool.name
    if dest.exists():
        raise ToolExportError(f"导出目标已存在,拒绝覆盖:{dest}")

    # 交付树 = 骨架 + 冻结补丁(确定性重建;.venv 等可再生件天然不在)
    shutil.copytree(host_copy, dest)
    patch = run_dir / "adaptation.patch"
    patch_bytes = patch.read_bytes() if patch.is_file() else b""
    if patch_bytes.strip():
        # cwd=dest 下必须给绝对路径 —— 相对 run_dir 的路径在这里失效
        got = subprocess.run(["git", "apply", str(patch.resolve())], cwd=dest,
                             capture_output=True, text=True)
        if got.returncode != 0:
            shutil.rmtree(dest)
            raise ToolExportError(f"补丁重放失败:{got.stderr[:400]}")

    # manifest verification 填充(agent 侧必须是 null —— 越权声明拦截)
    mf_p = dest / "tool.json"
    manifest = json.loads(mf_p.read_text(encoding="utf-8"))
    if manifest.get("verification") is not None:
        shutil.rmtree(dest)
        raise ToolExportError(
            "交付的 tool.json 已带非 null verification —— agent 越权声明,拒导出")
    manifest["verification"] = {
        "verdict": report.get("verdict_public") or verdict,
        "internal_verdict": verdict,
        "run_id": report.get("run_id"),
        "contract_sha256": tc_digest,
        "gate_report": "evidence/report.json",
        "replay_mode": "clean_adoption",
    }
    mf_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    # evidence/(EXPORT_ONLY:oracle/held-out 不在 run_dir 交付面,天然不进包)
    ev = dest / "evidence"
    ev.mkdir()
    for name in ("report.json", "adaptation_manifest.json", "adaptation.patch"):
        src = run_dir / name
        if src.is_file():
            shutil.copy2(src, ev / name)
    ver_dir = run_dir / "verification"
    if ver_dir.is_dir():
        shutil.copytree(ver_dir, ev / "verification")
    (ev / "provenance.json").write_text(json.dumps({
        "tool": tc.tool.name,
        "task_id": tc.task_id,
        "run_id": report.get("run_id"),
        "source": {"url": tc.source_repo.url,
                   "resolved_commit": tc.source_repo.resolved_commit,
                   "license": tc.source_repo.license,
                   "distribution": tc.source_repo.distribution},
        "tool_contract_sha256": tc_digest,
        "final_trace_sha256": report.get("final_trace_sha256"),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    for rel in (f"bin/{tc.tool.name}", "build.sh"):
        p = dest / rel
        if p.is_file():
            p.chmod(0o755)
    return dest
