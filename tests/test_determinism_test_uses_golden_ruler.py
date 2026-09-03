"""冻结包的判定测试与验收用同一把尺(incident-artifact-identity-zip-metadata-*,第五等价点)。

现象:真发能力 5/5、回归/策略全绿,净室 replay 只在 `test_workspace_output_is_deterministic`
分歧——该测试仍哈希原始字节(zip 成员 DOS 时间戳 2 秒窗口,主跑侥幸同窗、净室跨窗),而其余
四个等价点早已换成 zip 规范化黄金身份。包内不允许留第二把尺。

不变量:
  I1 装配器生成的判定测试断言 `_golden_sha(first) == _golden_sha(second)`;
  I2 公开测试前奏不再含 `_tree_sha`(第二尺清除);
  I3 行为上:两棵只差 zip 元数据的树在该尺下相等,成员字节不同则不等。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from repoproof.adoption.assembly import workspace_tool_assembler


def test_prelude_has_no_second_ruler() -> None:
    assert "_tree_sha" not in workspace_tool_assembler._TEST_PRELUDE


def test_determinism_assertion_compares_the_golden_identity(tmp_path: Path) -> None:
    import inspect

    source = inspect.getsource(workspace_tool_assembler)
    assert "assert _golden_sha(first) == _golden_sha(second)" in source
    assert "assert _tree_sha(first) == _tree_sha(second)" not in source


def _zip(members: list[tuple[str, bytes]], *, stamp: tuple, compression: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = compression
            archive.writestr(info, payload)
    return buffer.getvalue()


def test_the_shipped_ruler_ignores_zip_incidentals_only(tmp_path: Path) -> None:
    members = [("ppt/slide1.xml", b"<sld/>"), ("docProps/core.xml", b"<core/>")]
    one = tmp_path / "one"
    two = tmp_path / "two"
    three = tmp_path / "three"
    for root, blob in (
        (one, _zip(members, stamp=(2026, 9, 3, 16, 57, 30), compression=zipfile.ZIP_DEFLATED)),
        (two, _zip(list(reversed(members)), stamp=(2026, 9, 3, 16, 57, 32), compression=zipfile.ZIP_STORED)),
        (
            three,
            _zip(
                [("ppt/slide1.xml", b"<sld><sp/></sld>"), members[1]],
                stamp=(2026, 9, 3, 16, 57, 30),
                compression=zipfile.ZIP_DEFLATED,
            ),
        ),
    ):
        root.mkdir()
        (root / "report.pptx").write_bytes(blob)
    namespace: dict = {"__file__": str(tmp_path / "public_tests" / "t.py")}
    prelude = workspace_tool_assembler._TEST_PRELUDE.replace('os.environ["REPOPROOF_TOOL_BIN"]', '"unused"')
    exec(compile(prelude, "prelude", "exec"), namespace)  # noqa: S102 - the frozen test text is the object under test
    golden = namespace["_golden_sha"]
    assert golden(one) == golden(two)
    assert golden(one) != golden(three)
