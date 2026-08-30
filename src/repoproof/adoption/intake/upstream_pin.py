"""上游 pin 的**单一来源**:钉版树声明什么版本,全链就用哪一版。

`reference.lock.txt` 一旦缺席，整条链会**在三个地方各自静默降级**:

1. `confirm_tool_draft` 传 `reference_lock=""` → 装配器不写
   `controls/<task>/reference/requirements.lock.txt`;
2. 备轮 `pip download` 拿不到上游 pin → wheelhouse 里没有上游本体;
3. positive 彩排的预装步读不到那份 controls 锁 → 会话 venv 不装上游。

于是 `import <上游>` 在会话里必炸,却要等三轮修复耗尽,才以
`DEPENDENCY_ERROR` 的形式浮出来 —— 病因与症状隔了十万八千里。

修法不是在三处各打一个补丁,而是**让那份锁一定存在**:草稿束没写就从
钉版树自己声明的版本派生。用树里的版本、不是 PyPI 的最新版 —— pin 的
语义是"就这一版",去解析最新版等于把钉版偷偷放开。

派生不出来时返回空串:调用方各自决定是拒发(备轮)还是照旧留空
(装配)——本模块只负责"说出事实",不替人做判定。
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

_RELEASE_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,3}"
    r"(?:(?:a|b|rc)[0-9]+|\.(?:post|dev)[0-9]+)?$",
    re.IGNORECASE,
)


def normalize_dist_name(name: str) -> str:
    """PEP 503 归一化(`Foo_Bar.baz` 与 `foo-bar-baz` 是同一个分发)。"""
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


def _release_version_from_tag_name(tag: str, *, distribution: str) -> str:
    """Project a deliberately narrow release tag into a package version.

    Accepted shapes are ``1.2.3``, ``v1.2.3`` and
    ``<distribution>-1.2.3``.  A dotted numeric release is required.  This is
    intentionally narrower than arbitrary PEP 440 because a branch, commit or
    marketing tag must never silently become an install pin.
    """

    raw = str(tag or "").strip()
    if raw.startswith("refs/tags/"):
        raw = raw[len("refs/tags/") :]
    if not raw or re.search(r"[\s/@#]", raw):
        return ""
    candidate = raw[1:] if raw[:1] in {"v", "V"} else raw
    match = re.search(r"[0-9]", candidate)
    if match is None:
        return ""
    prefix = candidate[: match.start()].rstrip("-_.")
    version = candidate[match.start() :]
    if prefix and normalize_dist_name(prefix) != normalize_dist_name(distribution):
        return ""
    return version if _RELEASE_VERSION_RE.fullmatch(version) else ""


def _git_revision(path: Path, revision: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--verify", revision],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip().lower() if result.returncode == 0 else ""


def _verified_release_tag_version(
    upstream_dir: Path,
    *,
    distribution: str,
    requested_revision: str,
    resolved_commit: str,
) -> str:
    """Return a release version only when the fetched tag peels to ``HEAD``.

    Analysis checkouts are intentionally shallow and therefore often retain
    an annotated tag only as ``FETCH_HEAD`` rather than under ``refs/tags``.
    Both representations are admitted, but the peeled commit, current HEAD,
    requested tag name and frozen ``resolved_commit`` must all agree.
    """

    version = _release_version_from_tag_name(
        requested_revision,
        distribution=distribution,
    )
    commit = str(resolved_commit or "").strip().lower()
    if not version or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return ""
    root = Path(upstream_dir)
    if _git_revision(root, "HEAD^{commit}") != commit:
        return ""

    tag = str(requested_revision).strip()
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/") :]
    if _git_revision(root, f"refs/tags/{tag}^{{commit}}") == commit:
        return version

    # ``git fetch origin <tag>`` records the tag identity in FETCH_HEAD even
    # when the shallow checkout does not create a persistent tag ref.
    fetch_head = root / ".git" / "FETCH_HEAD"
    try:
        fetched = fetch_head.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    tag_marker = f"\ttag '{tag}' of "
    if not any(tag_marker in line for line in fetched.splitlines()):
        return ""
    if _git_revision(root, "FETCH_HEAD^{commit}") != commit:
        return ""
    return version


def upstream_version(
    upstream_dir: Path,
    *,
    import_module: str = "",
    distribution: str = "",
    requested_revision: str = "",
    resolved_commit: str = "",
) -> str:
    """从钉版上游树读**它自己声明的**版本;读不出返回空串。

    顺序:pyproject(PEP 621 / poetry)→ setup.cfg → *.egg-info/PKG-INFO →
    已识别 import package 的 ``__version__`` 字面量 → 与冻结 commit 一致
    的已验证发布 tag。所有来源都绑定钉版树；不会执行仓库代码，也不会去
    PyPI 猜最新版。
    """
    root = Path(upstream_dir)
    py = root / "pyproject.toml"
    if py.is_file():
        try:
            data = tomllib.loads(py.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        v = ((data.get("project") or {}).get("version")
             or ((data.get("tool") or {}).get("poetry") or {}).get("version"))
        if isinstance(v, str) and v.strip():
            return v.strip()
    cfg = root / "setup.cfg"
    if cfg.is_file():
        m = re.search(r"^\s*version\s*=\s*(\S+)\s*$",
                      cfg.read_text(encoding="utf-8", errors="replace"),
                      re.MULTILINE)
        if m:
            return m.group(1).strip()
    for info in sorted(root.glob("*.egg-info/PKG-INFO")):
        m = re.search(r"^Version:\s*(\S+)\s*$",
                      info.read_text(encoding="utf-8", errors="replace"),
                      re.MULTILINE)
        if m:
            return m.group(1).strip()
    module_parts = import_module.split(".") if import_module else []
    if module_parts and all(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) is not None
        for part in module_parts
    ):
        for base in (root, root / "src"):
            init_py = base.joinpath(*module_parts, "__init__.py")
            try:
                init_text = init_py.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for literal in re.findall(
                r'''^\s*__version__\s*=\s*["']([^"']+)["']\s*$''',
                init_text,
                re.MULTILINE,
            ):
                # ``__version__ = "unknown"`` is a common import-metadata
                # fallback in dynamic-version projects.  It is not an
                # installable release and must not outrank a verified tag.
                version = _release_version_from_tag_name(literal, distribution="")
                if version:
                    return version
    return _verified_release_tag_version(
        root,
        distribution=distribution,
        requested_revision=requested_revision,
        resolved_commit=resolved_commit,
    )


def pinned_upstream_dir(project_root: Path, resolved_commit: str) -> Path:
    """钉版树落点(与 tool_pipeline.ensure_pinned_upstream 同一约定)。"""
    return Path(project_root) / "upstream-cache" / f"upstream-{resolved_commit[:12]}"


def derive_reference_lock(
    project_root: Path,
    *,
    distribution: str,
    resolved_commit: str,
    import_module: str = "",
    requested_revision: str = "",
) -> str:
    """→ `"<dist>==<版本>\\n"`(带来源注释);派生不出时返回空串。"""
    return reference_lock_from_checkout(
        pinned_upstream_dir(project_root, resolved_commit),
        distribution=distribution,
        resolved_commit=resolved_commit,
        import_module=import_module,
        requested_revision=requested_revision,
    )


def reference_lock_from_checkout(
    checkout_dir: Path,
    *,
    distribution: str,
    resolved_commit: str,
    import_module: str = "",
    requested_revision: str = "",
) -> str:
    """Derive an exact pin from a checkout bound to the frozen commit.

    Intake owns a persistent analysis checkout before the formal
    ``upstream-<commit>`` cache exists. Reading the version there closes the
    new-repository bootstrap loop without consulting an index or executing
    upstream code. Dynamic versions remain admissible only when the requested
    release tag is bound to ``resolved_commit`` by git.
    """

    if not distribution or not resolved_commit:
        return ""
    version = upstream_version(
        Path(checkout_dir),
        import_module=import_module,
        distribution=distribution,
        requested_revision=requested_revision,
        resolved_commit=resolved_commit,
    )
    if not version:
        return ""
    return (f"# 由钉版上游树声明版本派生(commit {resolved_commit[:12]});\n"
            f"# 草稿束写了 reference.lock.txt 时以你写的为准。\n"
            f"{distribution}=={version}\n")
