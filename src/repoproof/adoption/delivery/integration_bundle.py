"""Integration Bundle(RFC-008 §9.1,EXPORT_ONLY)— 默认交付方式。

从一次已完成 run(成功或诚实失败)导出可移交产物包;绝不写用户
项目。铁律:
- held-out 验收(oracle/)任何内容不进 bundle——只导出公开测试;
- FAIL/BLOCKED 同样导出(当前产物 + 失败报告 + 下一步建议);
- bundle_manifest.json 记录每个文件的 sha256,可独立复核;
- 目标目录必须为空或不存在,绝不覆盖、绝不删除。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.delivery.apply_manifest import RESULT_EXPORT_READY, ApplyManifest


class BundleError(RuntimeError):
    pass


class BundleManifest(BaseModel):
    source_run: str
    task_id: str
    verdict: str
    status: str = RESULT_EXPORT_READY
    files: dict[str, str] = {}  # bundle 内相对路径 → sha256

    def to_dict(self) -> dict:
        return self.model_dump()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_tree(src: Path, dst: Path) -> None:
    """拷贝目录树,**不跟随符号链接**。

    独立验证发现:默认 copytree 解引用 symlink——公开测试目录里一个
    指向 oracle/ 的链接就能把 held-out 内容拷进 bundle。这里跳过链接
    并留痕,纵深防御。"""
    if not src.is_dir():
        return
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_symlink():
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            (out.parent / f"{out.name}.SKIPPED_SYMLINK.txt").write_text(
                f"跳过符号链接 {rel}(结果包不跟随链接)\n", encoding="utf-8")
            continue
        if p.is_file():
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)


_MIN_LEAK_BYTES = 32  # 空/平凡文件(如 "{}")内容相同不构成泄漏


def _scan_for_oracle_leak(bundle: Path, oracle_dir: Path) -> list[str]:
    """→ bundle 中内容与 oracle 树任一实质文件相同的相对路径(应为空)。"""
    if not oracle_dir.is_dir():
        return []
    oracle_hashes = {
        _sha256_file(p) for p in oracle_dir.rglob("*")
        if p.is_file() and not p.is_symlink() and p.stat().st_size >= _MIN_LEAK_BYTES
    }
    if not oracle_hashes:
        return []
    return [
        str(p.relative_to(bundle)) for p in sorted(bundle.rglob("*"))
        if p.is_file() and not p.is_symlink()
        and p.stat().st_size >= _MIN_LEAK_BYTES and _sha256_file(p) in oracle_hashes
    ]


def _guide_text(task_id: str, verdict: str, adapter_files: list[str]) -> str:
    ok = verdict.startswith("PASS")
    lines = [
        f"# 集成指南 — {task_id}",
        "",
        f"最终判定:**{verdict}**(由独立验证产生,AI 自述不算数)。",
        "",
    ]
    if ok and adapter_files:
        lines += [
            "## 如何合入你的项目",
            "",
            "1. 审查 `adapter/` 下的适配代码(全部由 AI 在隔离环境生成,已通过公开样例、",
            "   隐藏验收与干净环境复测);",
            "2. 将 `adapter/` 内容拷入你项目中你选定的适配位置;",
            "3. 按 `dependencies/DEPENDENCIES.md` 安装固定版本依赖;",
            "4. 运行 `tests/` 下的公开样例测试确认行为;",
            "5. 跑你自己的项目回归;",
            "6. 如需撤销,见 `rollback_plan.md`。",
        ]
    else:
        lines += [
            "## 本次未达成可用结论(诚实失败也交付)",
            "",
            "- `report.md` 列出失败原因与已完成的部分;",
            "- `adapter/` 内是当前进度产物(如为空,表示 AI 未产出适配文件);",
            "- 建议:阅读失败原因后调整样例/预算/目标,重新装配运行。",
        ]
    return "\n".join(lines) + "\n"


def _report_text(task_id: str, report: dict) -> str:
    cap = report.get("capability", {})
    reg = report.get("regression", {})
    lines = [
        f"# 结果报告 — {task_id}",
        "",
        f"- 最终判定:**{report.get('final_verdict', 'UNKNOWN')}**",
        f"- 能力验收:{cap.get('passed_checks', '?')}/{cap.get('total_checks', '?')} 通过",
        f"- 原项目回归:{reg.get('passed_checks', '?')}/{reg.get('total_checks', '?')} 通过",
        f"- 规则检查:{report.get('policy', {}).get('status', '?')}",
        f"- AI 结束方式:{report.get('agent', {}).get('exit_status', '?')}"
        f"(调用 {report.get('agent', {}).get('model_call_count', '?')} 次)",
        "",
        "## 判定依据(逐条)",
    ]
    for r in report.get("gate_reasons", []) or ["(无)"]:
        lines.append(f"- {r}")
    failed = report.get("capability_failed_tests") or []
    if failed:
        lines += ["", "## 未通过的公开验收点"]
        lines += [f"- {t}" for t in failed[:20]]
    return "\n".join(lines) + "\n"


def export_bundle(project_root: Path, run_dir: Path, dest: Path | None = None) -> dict:
    """导出 integration_bundle;返回 {ok, bundle_dir, manifest}。"""
    run_dir = run_dir.resolve()
    report_p = run_dir / "report.json"
    if not report_p.exists():
        raise BundleError(f"run 未完成或不完整:缺 {report_p}")
    report = json.loads(report_p.read_text(encoding="utf-8"))
    task_id = report.get("task_id") or run_dir.name.rsplit("-", 2)[0]
    verdict = report.get("final_verdict", "UNKNOWN")

    bundle = (dest or (run_dir / "integration_bundle")).resolve()
    if bundle.exists() and any(bundle.iterdir()):
        raise BundleError(f"目标目录非空,拒绝覆盖:{bundle}")
    oracle_dir = (project_root / "oracle" / task_id).resolve()
    if oracle_dir in (bundle, *bundle.parents):
        raise BundleError("bundle 不得落在 oracle 目录内")
    bundle.mkdir(parents=True, exist_ok=True)

    # adapter/ ← run 的 adaptation 区(FAIL 时可能为空——照样导出)
    adapter_dir = bundle / "adapter"
    adapter_dir.mkdir()
    adaptation_src = run_dir / "adaptation"
    adapter_files: list[str] = []
    if adaptation_src.is_dir():
        for p in sorted(adaptation_src.rglob("*")):
            if p.is_symlink() or not p.is_file():
                continue  # 不跟随链接(同 _copy_tree)
            rel = p.relative_to(adaptation_src)
            (adapter_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, adapter_dir / rel)
            adapter_files.append(str(rel))

    # patches/ ← 适配清单(上游 patch 台账;guided 任务通常为空清单)
    patches_dir = bundle / "patches"
    patches_dir.mkdir()
    am = run_dir / "adaptation_manifest.json"
    if am.exists():
        shutil.copy2(am, patches_dir / "adaptation_manifest.json")

    # dependencies/ ← 任务包(固定 commit + wheel 哈希)+ 说明
    deps_dir = bundle / "dependencies"
    deps_dir.mkdir()
    pkg = project_root / "contracts" / f"{task_id}.package.json"
    dist = commit = "见任务包"
    if pkg.exists():
        shutil.copy2(pkg, deps_dir / f"{task_id}.package.json")
        try:
            pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
            dist = pkg_data.get("distribution") or dist
            commit = (pkg_data.get("source_repo") or {}).get("resolved_commit", commit)
        except json.JSONDecodeError:
            pass
    (deps_dir / "DEPENDENCIES.md").write_text(
        f"# 依赖锁定\n\n- 目标能力包:`{dist}`\n- 固定版本 commit:`{commit}`\n"
        f"- 完整 wheel 哈希与镜像 digest:见同目录 `{task_id}.package.json`。\n",
        encoding="utf-8")

    # tests/ ← 只导出公开测试;held-out(oracle/)绝不进 bundle
    tests_dir = bundle / "tests"
    tests_dir.mkdir()
    contract_yaml = project_root / "contracts" / f"{task_id}.yaml"
    consumer_rel = ""
    if contract_yaml.exists():
        for line in contract_yaml.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("path:") and "fixtures/" in line:
                consumer_rel = line.split(":", 1)[1].strip()
                break
    if consumer_rel:
        pub_tests = project_root / consumer_rel / "public_tests"
        pub_examples = project_root / consumer_rel / "public_examples"
        if pub_tests.is_dir():
            _copy_tree(pub_tests, tests_dir / "public_tests")
        if pub_examples.is_dir():
            _copy_tree(pub_examples, tests_dir / "public_examples")

    # runtime/ ← 合同 + 复现说明
    runtime_dir = bundle / "runtime"
    runtime_dir.mkdir()
    if contract_yaml.exists():
        shutil.copy2(contract_yaml, runtime_dir / f"{task_id}.yaml")
    (runtime_dir / "REPRODUCE.md").write_text(
        "# 复现\n\n"
        f"- 镜像 digest:`{report.get('image_digest', 'UNKNOWN')}`\n"
        f"- 合同 sha256:`{report.get('contract_sha256', 'UNKNOWN')}`\n"
        "- 在 RepoProof 工作台:装配同名任务后点「真实运行」;"
        "或 CLI `repoproof agent-run --contract runtime/<task>.yaml`。\n",
        encoding="utf-8")

    # 三份说明 + 写回账本(EXPORT_ONLY:账本为空差异,占位供 Gate E)
    (bundle / "integration_guide.md").write_text(
        _guide_text(task_id, verdict, adapter_files), encoding="utf-8")
    (bundle / "report.md").write_text(_report_text(task_id, report), encoding="utf-8")
    (bundle / "rollback_plan.md").write_text(
        "# 回滚方案\n\n- EXPORT_ONLY 模式未写入你的项目,无需回滚;\n"
        "- 若你手工拷贝了 adapter/,删除拷入的文件即可(清单见 apply_manifest.json 的"
        " files_created,应用后由系统填写);\n"
        "- APPLY 模式的自动回滚在应用时生成 preimage 备份后启用。\n",
        encoding="utf-8")
    manifest = ApplyManifest(
        base_project_path_fingerprint="",
        base_tree_hash="",
        dependency_changes=[f"{dist}@{commit}"],
        result_state=RESULT_EXPORT_READY,
    )
    (bundle / "apply_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")

    # 导出后兜底扫描:bundle 中任何文件的内容哈希都不得等于 oracle
    # 树中任一文件(纵深防御:即使某条拷贝路径被绕过也会在此暴露)
    leaked = _scan_for_oracle_leak(bundle, oracle_dir)
    if leaked:
        shutil.rmtree(bundle, ignore_errors=True)
        raise BundleError(f"导出中止:检出隐藏验收内容进入结果包 {leaked}")

    files = {str(p.relative_to(bundle)): _sha256_file(p)
             for p in sorted(bundle.rglob("*")) if p.is_file()}
    bm = BundleManifest(source_run=run_dir.name, task_id=task_id,
                        verdict=verdict, files=files)
    (bundle / "bundle_manifest.json").write_text(
        json.dumps(bm.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return {"ok": True, "bundle_dir": str(bundle), "manifest": bm.to_dict()}
