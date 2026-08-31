from pathlib import Path
import re

import rispy


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
        records = rispy.loads(source)
        if not records:
            raise ValueError("输入中没有可导出的 RIS 记录")

        seen = set()
        retained = []
        for record in records:
            # The upstream serialization of each individual record is the
            # committed definition of an exact duplicate.
            fingerprint = rispy.dumps([record])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            retained.append(record)

        if not retained:
            raise ValueError("没有可导出的 RIS 文献记录")

        result = rispy.dumps(retained)
        if not result:
            raise ValueError("没有可导出的 RIS 文献记录")

        # rispy's list writer prefixes each record's TY line with an ordinal
        # presentation marker (for example, "1. TY  -").  That marker is not
        # part of RIS interchange syntax, so remove only this writer framing.
        result = re.sub(r"(?m)^\d+\.\s+(?=TY  -)", "", result)
        if not result.strip():
            raise ValueError("没有可导出的 RIS 文献记录")
        return result
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
        raise UserInputError("无法读取或整理 UTF-8 RIS 文献文件") from exc
    except Exception as exc:
        raise UserInputError("无法读取或整理 UTF-8 RIS 文献文件") from exc
