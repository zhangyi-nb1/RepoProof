"""feedparser-tool — CLI 骨架(harness 锁定件:argparse / exit 语义 / 错误分层)。

exit 语义(合同冻结):0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。
能力实现在 impl.py(agent 交付);本文件的结构改动 = 越权。
"""
import argparse
import sys
from pathlib import Path

from . import impl


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='feedparser-tool', description='将本地 RSS/Atom 订阅源文件解析为按原始顺序排列的条目标题与链接清单。')
    p.add_argument("input", help="输入文件(RSS/Atom XML)")
    p.add_argument("--out", help="输出文件(缺省写 stdout)")
    return p


def cli(argv=None) -> int:
    args = _parser().parse_args(argv)
    src = Path(args.input)
    if not src.is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1
    try:
        result = impl.extract(src)
    except impl.UserInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — 兜底即内部错误,语义=2
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result if result.endswith("\n") else result + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
