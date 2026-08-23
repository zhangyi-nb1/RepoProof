from pathlib import Path
import json
import chardet


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        path = Path(input_path)
        if not path.exists() or not path.is_file():
            raise UserInputError("input must be an existing regular file")
        data = path.read_bytes()
        if len(data) == 0:
            raise UserInputError("input must not be empty")
        result = chardet.detect(data)
    except UserInputError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise UserInputError(str(exc)) from exc

    if not isinstance(result, dict):
        raise UserInputError("chardet returned an invalid detection result")

    encoding = result.get("encoding") or "unknown"
    confidence = result.get("confidence")
    language = result.get("language") or ""

    try:
        confidence_value = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError) as exc:
        raise UserInputError("chardet returned an invalid confidence value") from exc

    if confidence_value < 0.0:
        confidence_value = 0.0
    elif confidence_value > 1.0:
        confidence_value = 1.0

    report = {
        "encoding": str(encoding),
        "confidence": round(confidence_value, 6),
        "language": str(language),
        "chardet_version": str(getattr(chardet, "__version__", getattr(chardet, "VERSION", "unknown"))),
    }
    return json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n"
