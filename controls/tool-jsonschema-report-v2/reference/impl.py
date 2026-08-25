"""reference:真调 pinned jsonschema 的参考实现(出题人材料,绝不交付)。"""
import json as _json
from pathlib import Path

import jsonschema


class UserInputError(ValueError):
    pass


def _pointer(err) -> str:
    parts = list(err.absolute_path)
    if not parts:
        return ""
    return "/" + "/".join(str(x) for x in parts)


def extract(input_path: Path) -> str:
    try:
        doc = _json.loads(input_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, ValueError) as e:
        raise UserInputError(str(e)) from e
    if not isinstance(doc, dict) or "schema" not in doc or "data" not in doc:
        raise UserInputError("top-level object must contain 'schema' and 'data'")
    try:
        validator = jsonschema.Draft202012Validator(doc["schema"])
        validator.check_schema(doc["schema"])
    except jsonschema.exceptions.SchemaError as e:
        raise UserInputError(f"invalid schema: {e.message}") from e
    errors = sorted(
        ({"path": _pointer(e), "message": e.message}
         for e in validator.iter_errors(doc["data"])),
        key=lambda d: (d["path"], d["message"]))
    report = {"valid": not errors, "error_count": len(errors), "errors": errors}
    return _json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
