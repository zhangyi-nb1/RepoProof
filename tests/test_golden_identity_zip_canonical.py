"""黄金比对必须按容器语义识别 zip 类产物(incident-artifact-identity-zip-metadata-*)。

现象:两个任务版本上,交付件解包后成员逐字节相同,只有 zip 成员顺序 / 压缩级别 / 条目时间戳不同
(pptx 参考实现两次运行相差 16 分钟;xlsx Agent 用 in_memory 写出不同顺序),逐字节黄金判 FAIL。
尺子把容器的偶然元数据当成了内容。

不变量:
  I1 `golden_file_identity(payload)`:能解析为 zip 的字节按 **排序后的 (成员名, 成员字节)** 求
     身份,与成员顺序、压缩级别、时间戳、extra 字段无关;成员字节不同则身份不同;非 zip 字节
     就是原始 sha256;
  I2 `golden_tree_sha256(root)` 以此为每文件身份(仍绑路径与可执行位),而证据清单的
     `tree_sha256` 保持原始字节完整性不变(冻结件的清单哈希不动);
  I3 导出到任务包的公开测试前奏 `_golden_sha` 与 Core 同尺(奇偶校验:同一棵树两边相等);
  I4 验收等价性(preflight 黄金、新输入抽查参考树匹配、可复现探针、公开 fixture 复用检查)比
     `golden_tree_sha256`,证据里的原始 `tree_sha256` 照旧记录。
"""

from __future__ import annotations

import hashlib
import inspect
import io
import zipfile
from pathlib import Path

from repoproof.adoption.assembly import workspace_tool_assembler
from repoproof.adoption.delivery.portable_workspace_runtime import golden_file_identity, golden_tree_sha256
from repoproof.execution.workspace_bundle import build_artifact_manifest


def _zip(members: list[tuple[str, bytes]], *, compression: int, stamp: tuple) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = compression
            archive.writestr(info, payload)
    return buffer.getvalue()


_MEMBERS = [
    ("[Content_Types].xml", b"<Types/>"),
    ("xl/workbook.xml", b"<workbook/>"),
    ("docProps/core.xml", b"<core/>"),
]


def test_zip_identity_ignores_order_compression_and_timestamps() -> None:
    a = _zip(_MEMBERS, compression=zipfile.ZIP_DEFLATED, stamp=(1980, 1, 1, 0, 0, 0))
    b = _zip(list(reversed(_MEMBERS)), compression=zipfile.ZIP_STORED, stamp=(2024, 6, 3, 12, 8, 58))
    assert a != b
    assert golden_file_identity(a) == golden_file_identity(b)
    changed = _zip(
        [(n, p if n != "xl/workbook.xml" else b"<workbook><sheet/></workbook>") for n, p in _MEMBERS],
        compression=zipfile.ZIP_DEFLATED,
        stamp=(1980, 1, 1, 0, 0, 0),
    )
    assert golden_file_identity(changed) != golden_file_identity(a)


def test_non_zip_bytes_keep_their_raw_sha256() -> None:
    payload = b"plain,csv\n1,2\n"
    assert golden_file_identity(payload) == hashlib.sha256(payload).hexdigest()
    assert (
        golden_file_identity(b"PK\x03\x04 not really a zip")
        == hashlib.sha256(b"PK\x03\x04 not really a zip").hexdigest()
    )


def _tree(root: Path, workbook: bytes) -> Path:
    (root / "output").mkdir(parents=True)
    (root / "README.md").write_text("# same\n", encoding="utf-8")
    (root / "output" / "book.xlsx").write_bytes(workbook)
    return root


def test_golden_tree_matches_while_raw_manifest_tree_differs(tmp_path: Path) -> None:
    left = _tree(tmp_path / "left", _zip(_MEMBERS, compression=zipfile.ZIP_DEFLATED, stamp=(1980, 1, 1, 0, 0, 0)))
    right = _tree(
        tmp_path / "right",
        _zip(list(reversed(_MEMBERS)), compression=zipfile.ZIP_STORED, stamp=(2024, 6, 3, 12, 8, 58)),
    )
    first, second = build_artifact_manifest(left), build_artifact_manifest(right)
    assert first.tree_sha256 != second.tree_sha256  # integrity hash still sees every byte
    assert golden_tree_sha256(left) == golden_tree_sha256(right)
    (right / "README.md").write_text("# changed\n", encoding="utf-8")
    assert golden_tree_sha256(left) != golden_tree_sha256(right)


def test_exported_public_test_prelude_is_the_same_ruler(tmp_path: Path) -> None:
    left = _tree(tmp_path / "left", _zip(_MEMBERS, compression=zipfile.ZIP_DEFLATED, stamp=(1980, 1, 1, 0, 0, 0)))
    right = _tree(
        tmp_path / "right",
        _zip(list(reversed(_MEMBERS)), compression=zipfile.ZIP_STORED, stamp=(2024, 6, 3, 12, 8, 58)),
    )
    namespace: dict = {"__file__": str(tmp_path / "public_tests" / "test_public_contract.py")}
    prelude = workspace_tool_assembler._TEST_PRELUDE.replace('os.environ["REPOPROOF_TOOL_BIN"]', '"unused"')
    exec(compile(prelude, "prelude", "exec"), namespace)  # noqa: S102 - the frozen test text is the object under test
    assert namespace["_golden_sha"](left) == namespace["_golden_sha"](right) == golden_tree_sha256(left)


def test_acceptance_equalities_compare_the_golden_identity() -> None:
    from repoproof.runner import product_preflight, tool_release
    from repoproof.ui.services import product_jobs

    assert "golden_tree_sha256(reference_output) != golden_tree_sha256(expected_path)" in inspect.getsource(
        product_preflight
    )
    release = inspect.getsource(tool_release)
    assert "golden_tree_sha256(artifact_dir) == golden_tree_sha256(expected_dir)" in release
    probe = inspect.getsource(product_jobs._assert_reference_reproducible)
    assert "golden_tree_sha256(expected_dir) != golden_tree_sha256(rerun_dir)" in probe
