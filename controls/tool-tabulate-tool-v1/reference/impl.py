from pathlib import Path
import csv
import io
import tabulate as _tabulate_module


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        raw = Path(input_path).read_bytes()
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UserInputError(f"input is not valid UTF-8 CSV: {exc}") from exc

    if text == "":
        raise UserInputError("input CSV is empty")

    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        rows = list(reader)
    except csv.Error as exc:
        raise UserInputError(f"malformed CSV: {exc}") from exc

    if not rows:
        raise UserInputError("input CSV is empty")

    headers = rows[0]
    if not headers:
        raise UserInputError("CSV header row is empty")

    width = len(headers)
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != width:
            raise UserInputError(
                f"CSV row {index} has {len(row)} fields; expected {width}"
            )

    try:
        rendered = _tabulate_module.tabulate(
            rows[1:],
            headers=headers,
            tablefmt="github",
            disable_numparse=True,
        )
    except Exception as exc:
        raise UserInputError(f"could not render CSV as Markdown table: {exc}") from exc

    return rendered + "\n"
