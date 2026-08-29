from pathlib import Path
from html.parser import HTMLParser
import json
import webcolors


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError("input must be a readable UTF-8 HTML file") from exc

    if not source.strip():
        raise UserInputError("input is empty")

    void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    accepted_properties = {"color", "background-color", "border-color"}

    def canonical_color(value: str) -> str:
        token = value.strip()
        if not token:
            raise UserInputError("color value is empty")
        try:
            if token.startswith("#"):
                rgb = webcolors.hex_to_rgb(token)
                return webcolors.rgb_to_hex(rgb).lower()
            return webcolors.name_to_hex(token, spec=webcolors.CSS3).lower()
        except (ValueError, TypeError) as exc:
            raise UserInputError(f"unsupported color value: {token!r}") from exc

    class PaletteParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.stack: list[str] = []
            self.colors: list[str] = []

        def _consume_attributes(self, attrs: list[tuple[str, str | None]]) -> None:
            for key, value in attrs:
                name = key.lower()
                if name in {"color", "bgcolor"}:
                    if value is None:
                        raise UserInputError(f"attribute {name!r} requires a color value")
                    self.colors.append(canonical_color(value))
                elif name == "style":
                    if value is None:
                        raise UserInputError("style attribute requires a value")
                    for declaration in value.split(";"):
                        declaration = declaration.strip()
                        if not declaration:
                            continue
                        if ":" not in declaration:
                            raise UserInputError("malformed inline style declaration")
                        property_name, property_value = declaration.split(":", 1)
                        if property_name.strip().lower() in accepted_properties:
                            self.colors.append(canonical_color(property_value))

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            name = tag.lower()
            self._consume_attributes(attrs)
            if name not in void_tags:
                self.stack.append(name)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._consume_attributes(attrs)

        def handle_endtag(self, tag: str) -> None:
            name = tag.lower()
            if name in void_tags or not self.stack or self.stack[-1] != name:
                raise UserInputError(f"mismatched closing tag: {tag!r}")
            self.stack.pop()

    try:
        parser = PaletteParser()
        parser.feed(source)
        parser.close()
        if parser.stack:
            raise UserInputError(f"unclosed tag: {parser.stack[-1]!r}")
        if not parser.colors:
            raise UserInputError("no recognizable colors found")
        return json.dumps({"colors": parser.colors}, ensure_ascii=False, separators=(",", ":"))
    except UserInputError:
        raise
    except (ValueError, TypeError) as exc:
        raise UserInputError("malformed HTML input") from exc
