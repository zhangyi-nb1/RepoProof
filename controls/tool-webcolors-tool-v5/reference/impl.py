from pathlib import Path
import json
import webcolors


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError("unable to read UTF-8 color-name input") from exc

    color_name = text.strip()
    if not color_name or "\n" in color_name or "\r" in color_name:
        raise UserInputError("input must contain exactly one non-empty CSS3 color name")

    try:
        rgb = webcolors.name_to_rgb(color_name, spec=webcolors.CSS3)
    except (ValueError, TypeError) as exc:
        raise UserInputError("input is not a valid CSS3 color name") from exc

    result = {
        "color_name": color_name,
        "rgb": {
            "red": rgb.red,
            "green": rgb.green,
            "blue": rgb.blue,
        },
    }
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
