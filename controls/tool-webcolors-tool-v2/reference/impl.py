import json
import re
from pathlib import Path

import webcolors


class UserInputError(ValueError):
    pass


_DECLARATION_RE = re.compile(
    r"(?:^|[;{\s])(?:color|background-color|border-color|outline-color)\s*:\s*"
    r"(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)|[a-zA-Z]+)",
    re.IGNORECASE,
)
_ATTRIBUTE_RE = re.compile(
    r"\b(?:color|bgcolor)\s*=\s*['\"]?"
    r"(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|[a-zA-Z]+)",
    re.IGNORECASE,
)
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)


def _to_rgb(value: str) -> tuple[int, int, int]:
    try:
        match = _RGB_RE.fullmatch(value)
        if match:
            rgb = tuple(int(part) for part in match.groups())
            if any(channel > 255 for channel in rgb):
                raise ValueError("RGB channel outside 0..255")
            return rgb
        if value.startswith("#"):
            return tuple(webcolors.hex_to_rgb(value))
        return tuple(webcolors.name_to_rgb(value.lower(), spec=webcolors.CSS3))
    except (TypeError, ValueError) as exc:
        raise UserInputError(f"invalid color value: {value}") from exc


def extract(input_path: Path) -> str:
    try:
        raw = input_path.read_bytes()
        if not raw.strip():
            raise UserInputError("empty input")
        html = raw.decode("utf-8")
    except UserInputError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError("malformed input") from exc

    values = [match.group(1) for match in _DECLARATION_RE.finditer(html)]
    values.extend(match.group(1) for match in _ATTRIBUTE_RE.finditer(html))

    colors = {}
    for value in values:
        rgb = _to_rgb(value)
        try:
            hex_value = webcolors.rgb_to_hex(rgb).lower()
        except (TypeError, ValueError) as exc:
            raise UserInputError(f"invalid color value: {value}") from exc
        red, green, blue = rgb
        grayscale = round(0.2126 * red + 0.7152 * green + 0.0722 * blue)
        colors[hex_value] = {
            "hex": hex_value,
            "rgb": [red, green, blue],
            "grayscale": grayscale,
        }

    ordered = [colors[key] for key in sorted(colors)]
    return json.dumps(
        {"colors": ordered, "count": len(ordered)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
