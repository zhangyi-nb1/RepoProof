from pathlib import Path
import json

from markdown_it import MarkdownIt


class UserInputError(ValueError):
    pass


def _plain_inline_text(children) -> str:
    parts: list[str] = []
    for child in children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append("\n")
    return "".join(parts)


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UserInputError(f"cannot read UTF-8 Markdown input: {exc}") from exc

    if not source.strip():
        raise UserInputError("Markdown input is empty")

    try:
        tokens = MarkdownIt("commonmark").parse(source)
    except Exception as exc:
        raise UserInputError(f"cannot parse Markdown input: {exc}") from exc

    headings: list[dict[str, object]] = []
    links: list[dict[str, str]] = []
    code_blocks: list[dict[str, str]] = []

    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            text = _plain_inline_text(inline.children) if inline and inline.type == "inline" else ""
            try:
                level = int(token.tag[1:])
            except (ValueError, IndexError) as exc:
                raise UserInputError(f"invalid heading token: {token.tag!r}") from exc
            headings.append({"level": level, "text": text})
        elif token.type == "fence":
            info = token.info.strip()
            language = info.split(None, 1)[0] if info else ""
            code_blocks.append({"language": language, "code": token.content})

        if token.type != "inline":
            continue

        active_links: list[int] = []
        for child in token.children or []:
            if child.type == "link_open":
                href = child.attrGet("href") or ""
                links.append({"href": href, "text": ""})
                active_links.append(len(links) - 1)
            elif child.type == "link_close":
                if active_links:
                    active_links.pop()
            elif child.type in ("text", "code_inline"):
                for link_index in active_links:
                    links[link_index]["text"] += child.content
            elif child.type in ("softbreak", "hardbreak"):
                for link_index in active_links:
                    links[link_index]["text"] += "\n"

    result = {
        "headings": headings,
        "links": links,
        "code_blocks": code_blocks,
    }
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
