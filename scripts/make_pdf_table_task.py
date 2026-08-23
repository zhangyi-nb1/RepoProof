"""tool-pdf-table-v1 的装配调用(M1 真跑段;留仓 = 装配参数可复现可审)。

样例源:三个 PDF 取自 pinned 上游自带测试集(tests/pdfs;G2 第二层
"上游行为一致性"思路的 M1 手工化身),期望由 reference 同款渲染直连
生成并人工过目;held-out = federal-register(尾部,文件本体只进 oracle)。

用法:.venv/bin/python scripts/make_pdf_table_task.py <example_src_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repoproof.adoption.assembly.tool_assembler import assemble_tool_task  # noqa: E402
from repoproof.domain.models import ToolInterface, ToolInterfaceIO, ToolSpec  # noqa: E402

PINNED_COMMIT = "7d4f2f582f2d99f9e60ba522fdf7afd2f6d54c62"   # v0.11.10

SPEC = ToolSpec(
    name="pdf-table",
    summary="从 PDF 提取全部表格,输出 GitHub-flavored Markdown",
    interface=ToolInterface(
        usage="pdf-table <input.pdf> [--out FILE]",
        input=ToolInterfaceIO(kind="file", format="PDF"),
        output=ToolInterfaceIO(kind="stdout", format="markdown-table"),
        exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}))

GOAL = (
    "把 pdfplumber 的表格提取能力包装为本地 CLI 工具 pdf-table:输入一个 PDF,"
    "输出其中全部表格的 Markdown 渲染。渲染规范(行为定义):按文档序遍历每页"
    "每表;每表第一行为表头行,其后一行 |---|---|… 分隔,再逐行数据;单元格内"
    "空白(含换行)折叠为单个空格,None 单元格渲染为空串;表与表之间空一行;"
    "输出以单个换行结尾。无表格的合法 PDF 与无法解析的输入都属用户错误"
    "(抛 UserInputError → exit 1)。")

EXAMPLES = [
    {"input": "--help", "expected": "contains:usage"},
    {"input_file": "inputs/warn-report.pdf",
     "expected": "contains:| Notice Date | Effective | Received | Company "
                 "| City | No. Of | Layoff/Closure |"},
    {"input_file": "inputs/table-curves.pdf",
     "expected_file": "expected/table-curves.md"},
    # held-out(split 取尾部;文件本体只进 oracle)
    {"input_file": "inputs/federal-register.pdf",
     "expected": "contains:| Labor cost | Parts cost | Cost per product |"},
]

REFERENCE_IMPL = '''"""reference:真调 pinned pdfplumber 的参考实现(出题人提供,绝不交付)。"""
from pathlib import Path

import pdfplumber


class UserInputError(ValueError):
    """输入内容级错误(格式坏/不可解析/无表格)。"""


def _cell(c) -> str:
    return " ".join(str(c).split()) if c is not None else ""


def extract(input_path: Path) -> str:
    try:
        with pdfplumber.open(input_path) as pdf:
            tables = [t for page in pdf.pages
                      for t in (page.extract_tables() or []) if t]
    except Exception as e:  # 打不开/解析不了 = 用户错误(PdfminerException 等)
        raise UserInputError(f"cannot parse as PDF: {type(e).__name__}: {e}") from e
    if not tables:
        raise UserInputError("no tables found in PDF")
    out: list[str] = []
    for t in tables:
        rows = [[_cell(c) for c in row] for row in t]
        header, body = rows[0], rows[1:]
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "|".join(["---"] * len(header)) + "|")
        out.extend("| " + " | ".join(r) + " |" for r in body)
        out.append("")
    return "\\n".join(out).rstrip() + "\\n"
'''

REFERENCE_LOCK = """cffi==2.1.1
charset-normalizer==3.5.1
cryptography==50.0.0
pdfminer.six==20260107
pdfplumber==0.11.10
pillow==12.3.0
pycparser==3.0
pypdfium2==5.13.0
"""


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src = Path(sys.argv[1]).expanduser().resolve()
    info = assemble_tool_task(
        root,
        goal=GOAL,
        repo_url="https://github.com/jsvine/pdfplumber",
        resolved_commit=PINNED_COMMIT,
        distribution="pdfplumber",
        import_module="pdfplumber",
        license_id="MIT",
        tool=SPEC,
        examples=EXAMPLES,
        example_src_dir=src,
        reference_impl=REFERENCE_IMPL,
        reference_lock=REFERENCE_LOCK,
    )
    print(f"task_id={info['task_id']} public={info['public']} held={info['held']}")
    for f in info["files"]:
        print("  ", f)
    print("next:", info["next"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
