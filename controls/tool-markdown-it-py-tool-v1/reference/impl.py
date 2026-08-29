from __future__ import annotations

import json
from pathlib import Path

from markdown_it import MarkdownIt


class UserInputError(ValueError):
    pass


def _inline_text(children: list[object] | None) -> str:
    parts: list[str] = []
    for child in children or []:
        token_type = child.type
        if token_type in {"softbreak", "hardbreak"}:
            parts.append(" ")
        elif token_type in {"text", "code_inline", "html_inline", "image"}:
            parts.append(child.content)
    return "".join(parts)


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError(f"cannot read UTF-8 Markdown input: {exc}") from exc
    if not source.strip():
        raise UserInputError("Markdown input is empty")
    try:
        tokens = MarkdownIt().parse(source)
    except Exception as exc:
        raise UserInputError(f"malformed Markdown input: {exc}") from exc

    headings: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    code_blocks: list[dict[str, object]] = []
    order = 0

    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            if inline.type == "inline":
                headings.append({
                    "order": order,
                    "level": int(token.tag[1:]),
                    "text": _inline_text(inline.children),
                })
                order += 1
        if token.type == "inline":
            open_links: list[dict[str, object]] = []
            for child in token.children or []:
                if child.type == "link_open":
                    attrs = child.attrs or {}
                    open_links.append({"target": attrs.get("href", ""), "parts": []})
                elif child.type == "link_close":
                    if open_links:
                        link = open_links.pop()
                        links.append({
                            "order": order,
                            "label": "".join(link["parts"]),
                            "target": link["target"],
                        })
                        order += 1
                else:
                    value = " " if child.type in {"softbreak", "hardbreak"} else (
                        child.content if child.type in {"text", "code_inline", "html_inline", "image"} else ""
                    )
                    for link in open_links:
                        link["parts"].append(value)
        elif token.type == "fence":
            info_parts = token.info.strip().split()
            code_blocks.append({
                "order": order,
                "language": info_parts[0] if info_parts else "",
                "content": token.content,
            })
            order += 1

    return json.dumps(
        {"headings": headings, "links": links, "code_blocks": code_blocks},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
