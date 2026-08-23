from pathlib import Path
import json
import yaml


class UserInputError(ValueError):
    pass


def _stringify_mapping_keys(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(key, str):
                out_key = key
            elif key is None:
                out_key = "null"
            elif isinstance(key, bool):
                out_key = "true" if key else "false"
            elif isinstance(key, (int, float)):
                out_key = str(key)
            else:
                raise UserInputError(f"unsupported YAML mapping key type: {type(key).__name__}")
            result[out_key] = _stringify_mapping_keys(item)
        return result
    if isinstance(value, list):
        return [_stringify_mapping_keys(item) for item in value]
    return value


def extract(input_path: Path) -> str:
    try:
        raw = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise UserInputError(f"input is not valid UTF-8: {exc}") from exc

    if not raw.strip():
        raise UserInputError("empty YAML input")

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise UserInputError(f"malformed YAML input: {exc}") from exc

    if data is None:
        raise UserInputError("YAML input must not be null or empty")

    data = _stringify_mapping_keys(data)

    try:
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as exc:
        raise UserInputError(f"YAML value cannot be represented as JSON: {exc}") from exc
