import re
from dataclasses import replace

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "­": "",
    " ": " ",
}

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    for char, replacement in LIGATURES.items():
        text = text.replace(char, replacement)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _template(line: str) -> str:
    return _DIGITS.sub("#", line.strip())


def footer_templates(blocks: list) -> set[str]:
    pages = {block.page for block in blocks}
    if len(pages) < 2:
        return set()
    seen: dict[str, set[int]] = {}
    for block in blocks:
        if block.kind != "text":
            continue
        for line in block.content.split("\n"):
            if line.strip():
                seen.setdefault(_template(line), set()).add(block.page)
    return {template for template, on_pages in seen.items() if on_pages == pages}


def strip_footers(blocks: list) -> list:
    footers = footer_templates(blocks)
    if not footers:
        return list(blocks)
    result = []
    for block in blocks:
        if block.kind != "text":
            result.append(block)
            continue
        kept = [
            line for line in block.content.split("\n") if _template(line) not in footers
        ]
        content = "\n".join(kept).strip()
        if content:
            result.append(replace(block, content=content))
    return result


def normalize(blocks: list) -> list:
    cleaned = []
    for block in strip_footers(blocks):
        content = clean_text(block.content)
        if content:
            cleaned.append(replace(block, content=content))
    return cleaned
