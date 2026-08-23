"""reference:真调 pinned pdfplumber 的参考实现(出题人提供,绝不交付)。"""
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
    return "\n".join(out).rstrip() + "\n"
