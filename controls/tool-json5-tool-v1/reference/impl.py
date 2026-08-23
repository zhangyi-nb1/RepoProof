from pathlib import Path
import json
import json5


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserInputError(f"could not read input: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise UserInputError(f"input is not valid UTF-8: {exc}") from exc

    if not text.strip():
        raise UserInputError("empty input")

    try:
        value = json5.loads(text)
    except Exception as exc:
        raise UserInputError(f"malformed JSON5 input: {exc}") from exc

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise UserInputError(f"value cannot be represented as strict JSON: {exc}") from exc
