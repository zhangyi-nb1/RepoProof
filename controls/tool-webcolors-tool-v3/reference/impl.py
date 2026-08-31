import json
from pathlib import Path

import webcolors


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UserInputError("无法读取 UTF-8 输入文件") from exc

    token = text.strip()
    if not token or len(token.split()) != 1:
        raise UserInputError("输入必须恰好包含一个非空颜色标记")

    try:
        if token.startswith("#"):
            color = webcolors.hex_to_rgb(token)
        else:
            color = webcolors.name_to_rgb(token, spec=webcolors.CSS3)
    except (ValueError, TypeError) as exc:
        raise UserInputError("不支持或格式错误的 CSS3 颜色") from exc

    red, green, blue = int(color[0]), int(color[1]), int(color[2])
    luma = (299 * red + 587 * green + 114 * blue + 500) // 1000
    gray_level = (luma * 7 + 127) // 255

    result = {
        "input": token,
        "rgb": {"red": red, "green": green, "blue": blue},
        "luma": luma,
        "gray_level": gray_level,
        "msp432_pattern": f"{gray_level:03b}",
    }
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
