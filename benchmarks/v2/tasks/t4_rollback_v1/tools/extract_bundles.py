"""T4 特性包提取器:从三个 PASS run 的 adaptation.patch 提炼冻结特性包。

决定性流程(可重跑,需 runs/ 在盘):
1. 对每特性:S0(bench 副本)CoW 抓痕 → git apply 原补丁 → 收割 created
   文件(字节与 mode 原样)入 features/<fid>/created/;
2. 原补丁按 "diff --git" 分节,modified 文件的节**逐字节原样**拼为
   features/<fid>/modified.patch(保留 index 行,--3way 需要);
3. feature.yaml 记 provenance(origin run/model/verdict/补丁 sha256)、
   文件清单、依赖增量、回滚类;
4. FeatureBundle.load 校验闭合。

变体依据(2026-08-11 取证,见 T4v1 预注册):
- F1 = T1 order-6(gpt-5.6,自带 tests/test_sdk_mcp.py);
- F2 = T2v4 order-20(gpt-5.5,守卫式惰性 shim 与 F1 组合相容;
  order-21 的根级 mcp/ stub 无条件遮蔽真 SDK,实测使 F1 在 S2 崩,落选);
- F3 = T3v5 order-40(gpt-5.6,T3 唯一真 PASS,sidecar 路线)。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

RP = Path(__file__).resolve().parents[5]
BENCH_SRC = Path.home() / "RepoProofBench/offerclaw-t3-browser-use"
OUT = Path(__file__).resolve().parents[1] / "features"
WORK = Path("/tmp/_t4_eng/extract")

FEATURES = [
    {
        "feature_id": "f1_fastapi_mcp",
        "feature_name": "FastAPI-MCP experimental endpoint (T1)",
        "run_id": "t1-offerclaw-fastapi-mcp-v1-20260810-002354",
        "model": "gpt-5.6",
        "source_repo": "https://github.com/tadata-org/fastapi_mcp",
        "source_commit": "e5cad13cabfc725bbcb047e526816d887d96da62",
        "created": ["sdk_mcp.py", "tests/test_sdk_mcp.py"],
        "modified": ["rag_api.py", "requirements.txt"],
        "dependency_delta": ["fastapi-mcp==0.4.0", "mcp==1.29.0"],
        "rollback_classes": ["PURE_FILE", "DEPENDENCY_LOCK"],
    },
    {
        "feature_id": "f2_open_deep_research",
        "feature_name": "Open Deep Research jobs (T2)",
        "run_id": "t2-offerclaw-open-deep-research-v4-20260810-200119",
        "model": "gpt-5.5",
        "source_repo": "https://github.com/langchain-ai/open_deep_research",
        "source_commit": "20aaa0d422bd290c83f93574810ef1244e8d5955",
        "created": ["fixtures/fake_llm_server.py", "research_jobs.py",
                    "research_jobs.sqlite3"],
        "modified": ["rag_api.py", "requirements.txt"],
        "dependency_delta": [],   # 零宿主依赖增量:上游经 ../upstream 运行时 vendor
        "rollback_classes": ["PURE_FILE", "DERIVED_DATA"],
        "notes": "运行时布局要求:<栈根>/../upstream = open_deep_research@20aaa0d 快照",
    },
    {
        "feature_id": "f3_apply_assist",
        "feature_name": "Browser Use Apply Assistant (T3)",
        "run_id": "t3-offerclaw-browser-use-v5-20260811-182535",
        "model": "gpt-5.6",
        "source_repo": "https://github.com/browser-use/browser-use",
        "source_commit": "32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4",
        "created": ["apply_assist.py", "apply_assist_sidecar.py",
                    "docs/apply_assist.md", "requirements-apply-assist.txt",
                    "scripts/build_apply_assist_sidecar.sh"],
        "modified": ["rag_api.py", "requirements.txt"],
        "dependency_delta": [],   # 宿主侧零增量;sidecar 钉版在 requirements-apply-assist.txt
        "rollback_classes": ["PURE_FILE", "DEPENDENCY_LOCK"],
        "notes": "sidecar venv 经 scripts/build_apply_assist_sidecar.sh 构建,"
                 "APPLY_ASSIST_SIDECAR_PYTHON 显式指定",
    },
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def split_patch(patch_text: str) -> dict[str, str]:
    """按 diff --git 分节;键 = b/ 路径。节文本逐字节保留。"""
    sections: dict[str, str] = {}
    cur_key, cur_lines = None, []
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur_key:
                sections[cur_key] = "".join(cur_lines)
            parts = line.split()
            cur_key = parts[3][2:] if len(parts) >= 4 else parts[2][2:]
            cur_lines = [line]
        elif cur_key:
            cur_lines.append(line)
    if cur_key:
        sections[cur_key] = "".join(cur_lines)
    return sections


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    for spec in FEATURES:
        fid = spec["feature_id"]
        patch_path = RP / "runs" / spec["run_id"] / "adaptation.patch"
        if not patch_path.is_file():
            print(f"FATAL: 缺原补丁 {patch_path}", file=sys.stderr)
            return 2
        out = OUT / fid
        if out.exists():
            shutil.rmtree(out)
        (out / "created").mkdir(parents=True)

        # 1) 抓痕收割 created(字节与 mode)
        scratch = WORK / fid
        subprocess.run(["cp", "-Rc", str(BENCH_SRC), str(scratch)], check=True)
        (scratch / "HOST_BASELINE_MANIFEST.json").unlink(missing_ok=True)
        subprocess.run(["git", "-C", str(scratch), "apply", str(patch_path)],
                       check=True)
        for rel in spec["created"]:
            src = scratch / rel
            dest = out / "created" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        # 2) modified 节逐字节拼装
        sections = split_patch(patch_path.read_text(encoding="utf-8",
                                                    errors="surrogateescape"))
        missing = [m for m in spec["modified"] if m not in sections]
        if missing:
            print(f"FATAL: {fid} 补丁缺节 {missing}", file=sys.stderr)
            return 2
        (out / "modified.patch").write_text(
            "".join(sections[m] for m in spec["modified"]),
            encoding="utf-8", errors="surrogateescape")

        # 3) feature.yaml
        meta = {
            "feature_id": fid,
            "feature_name": spec["feature_name"],
            "origin_run_id": spec["run_id"],
            "origin_model": spec["model"],
            "origin_verdict": "PASS_ADAPTED",
            "origin_patch_sha256": sha256(patch_path),
            "source_repo": spec["source_repo"],
            "source_commit": spec["source_commit"],
            "host_commit": "5b2d00e72ece656b76fc55c004b3c6e7d95bffdf",
            "files_created": sorted(spec["created"]),
            "files_modified": list(spec["modified"]),
            "requires_features": [],   # 代码级独立;composite 模式在 apply 时显式声明
            "dependency_delta": spec["dependency_delta"],
            "rollback_classes": spec["rollback_classes"],
            "notes": spec.get("notes", ""),
        }
        (out / "feature.yaml").write_text(
            yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        print(f"{fid}: created={len(spec['created'])} modified={len(spec['modified'])} "
              f"patch_sha={meta['origin_patch_sha256'][:12]}")

    # 4) 闭合校验
    sys.path.insert(0, str(RP / "src"))
    from repoproof.adoption.delivery.feature_stack import FeatureBundle
    for spec in FEATURES:
        FeatureBundle.load(OUT / spec["feature_id"])
        print(f"{spec['feature_id']}: FeatureBundle.load OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
