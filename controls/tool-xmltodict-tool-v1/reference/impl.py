"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

import json

import xmltodict


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    try:
        data = xmltodict.parse(text)
    except Exception as e:          # expat 解析错=用户输入错误
        raise UserInputError(str(e)) from e
    return json.dumps(data, ensure_ascii=False, indent=2)
