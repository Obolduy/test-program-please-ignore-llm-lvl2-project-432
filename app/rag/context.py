import re

MAX_CONTEXT_CHARS = 6000

INSTRUCTION = """Ты получаешь КОНТЕКСТ — фрагменты документов поставщика.
Правила:
1. Отвечай только по контексту. Нет данных — не выдумывай, добавь имя поля в missing_fields.
2. Каждое утверждение подтверждай источником: chunk_id из скобки [chunk_id | ...].
3. В sources перечисли только те chunk_id, которые есть в контексте выше.
4. Уверенность оценивай честно: мало данных — ниже.
"""

_HEADER = re.compile(r"^\[([a-z0-9]+) \|", flags=re.MULTILINE)


def source_header(chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    parts = [chunk["chunk_id"], chunk.get("filename") or metadata.get("doc_id", "")]
    if metadata.get("page"):
        parts.append(f"стр. {metadata['page']}")
    if metadata.get("section"):
        parts.append(metadata["section"])
    return "[" + " | ".join(str(part) for part in parts) + "]"


def build_context(chunks: list[dict], *, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    parts: list[str] = []
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    total = 0

    for chunk in chunks:
        text = chunk["text"].strip()
        if chunk["chunk_id"] in seen_ids or text in seen_texts:
            continue
        piece = source_header(chunk) + "\n" + text
        if parts and total + len(piece) > max_chars:
            break
        seen_ids.add(chunk["chunk_id"])
        seen_texts.add(text)
        parts.append(piece)
        total += len(piece) + 2

    return "\n\n".join(parts)


def context_chunk_ids(context: str) -> set[str]:
    return set(_HEADER.findall(context))
