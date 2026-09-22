import re
import uuid

from app.parsers.pdf import Block

CHUNK_SIZE = 700
CHUNK_OVERLAP = 120

_ARTICUL = re.compile(r"\b[A-Z]{2,5}-[A-Z0-9]{2,6}\b")
_BRAND_FIELD = re.compile(r"Бренд:\s*([^;\n]+)")
_BRAND_QUOTED = re.compile(r"«([А-ЯЁA-Z][^»\s]*)")


def chunk_blocks(
    blocks: list[Block],
    doc_id: str,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    chunks: list[dict] = []
    for block in blocks:
        parts = (
            _split_rows(block.content, size)
            if block.kind == "table"
            else _split_text(block.content, size, overlap)
        )
        chunks += [_chunk(part, block, doc_id) for part in parts]
    for ordinal, chunk in enumerate(chunks):
        chunk["ordinal"] = ordinal
    return chunks


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            if space > start:
                end = space
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = end - overlap
    return parts


def _split_rows(text: str, size: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    length = 0
    for row in text.split("\n"):
        if current and length + len(row) > size:
            parts.append("\n".join(current))
            current, length = [], 0
        current.append(row)
        length += len(row) + 1
    if current:
        parts.append("\n".join(current))
    return [part for part in parts if part.strip()]


def _chunk(text: str, block: Block, doc_id: str) -> dict:
    metadata = {"doc_id": doc_id, "page": block.page, "section": block.section}
    articul = _ARTICUL.search(text)
    if articul:
        metadata["articul"] = articul.group(0)
    brand = _BRAND_FIELD.search(text) or _BRAND_QUOTED.search(text)
    if brand:
        metadata["brand"] = brand.group(1).strip()
    return {"id": uuid.uuid4().hex[:12], "text": text, "metadata": metadata}
