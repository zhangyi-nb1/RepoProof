from pathlib import Path
import json
import webcolors


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        raw = input_path.read_text(encoding="utf-8")
        if not raw.strip():
            raise UserInputError("input is empty")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise UserInputError("input must be a JSON object")
        if set(payload) != {"color"}:
            raise UserInputError("input must contain only the color field")
        color = payload["color"]
        if not isinstance(color, str):
            raise UserInputError("color must be a string")

        rgb = webcolors.hex_to_rgb(color)
        red, green, blue = int(rgb.red), int(rgb.green), int(rgb.blue)
    except UserInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise UserInputError(str(exc) or "invalid color input") from exc

    grayscale = (299 * red + 587 * green + 114 * blue + 500) // 1000
    digital_level = 1 if grayscale >= 128 else 0
    result = {
        "source_hex": f"#{red:02x}{green:02x}{blue:02x}",
        "red": red,
        "green": green,
        "blue": blue,
        "grayscale": grayscale,
        "digital_level": digital_level,
        "sensor_state": "LIGHT" if digital_level else "DARK",
    }
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
