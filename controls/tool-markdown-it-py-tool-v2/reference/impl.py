from pathlib import Path
import json
import re

from markdown_it import MarkdownIt


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UserInputError("input must be a readable UTF-8 Markdown file") from exc

    if not source.strip():
        raise UserInputError("input Markdown file is empty")

    try:
        tokens = MarkdownIt().parse(source)
    except Exception as exc:
        raise UserInputError("malformed Markdown input") from exc

    def normalise(parts: list[str]) -> str:
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def visible_text(children) -> str:
        parts = []
        for child in children or []:
            if child.type in {"text", "code_inline", "image"}:
                parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                parts.append(" ")
        return normalise(parts)

    headings = []
    links = []
    code_blocks = []

    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline is not None and inline.type == "inline":
                headings.append({
                    "level": int(token.tag[1:]),
                    "text": visible_text(inline.children),
                })

        if token.type == "fence":
            info = token.info.strip()
            code_blocks.append({
                "language": info.split(None, 1)[0] if info else "",
                "code": token.content,
            })

        if token.type == "inline":
            children = token.children or []
            position = 0
            while position < len(children):
                child = children[position]
                if child.type != "link_open":
                    position += 1
                    continue

                href = child.attrGet("href") or ""
                depth = 1
                position += 1
                label_tokens = []
                while position < len(children) and depth:
                    current = children[position]
                    if current.type == "link_open":
                        depth += 1
                    elif current.type == "link_close":
                        depth -= 1
                        if depth == 0:
                            break
                    label_tokens.append(current)
                    position += 1

                links.append({
                    "href": href,
                    "text": visible_text(label_tokens),
                })
                position += 1

    result = {
        "headings": headings,
        "links": links,
        "code_blocks": code_blocks,
    }
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
