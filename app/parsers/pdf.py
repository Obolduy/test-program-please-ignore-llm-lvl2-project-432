import io
from dataclasses import dataclass, field

import pdfplumber

HEADING_MAX_CHARS = 60
HEADING_MAX_WORDS = 7


class PdfNoTextLayer(Exception):
    pass


@dataclass
class Block:

    kind: str
    content: str
    page: int
    section: str = ""
    rows: list[list[str]] = field(default_factory=list)


def looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or line.endswith((".", ";", ",", ":")):
        return False
    if line.isupper() and len(line) < HEADING_MAX_CHARS:
        return True
    return len(line) < HEADING_MAX_CHARS and len(line.split()) <= HEADING_MAX_WORDS


def table_to_text(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = [cell.strip() for cell in rows[0]]
    two_column_spec = len(header) == 2 and header[0].lower() in ("параметр", "характеристика")
    lines = []
    for row in rows[1:]:
        cells = [cell.strip() for cell in row]
        if two_column_spec:
            lines.append(f"{cells[0]}: {cells[1] if len(cells) > 1 else ''}")
        else:
            lines.append("; ".join(f"{h}: {c}" for h, c in zip(header, cells) if c))
    return "\n".join(lines)


def _normalize_cells(rows) -> list[list[str]]:
    return [[(cell or "").strip() for cell in row] for row in rows]


def parse_pdf(data: bytes) -> list[Block]:
    blocks: list[Block] = []
    had_text = False

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            lines = page.extract_text_lines() or []
            if lines:
                had_text = True
            tables = [
                (table.bbox[1], _normalize_cells(table.extract()))
                for table in page.find_tables()
            ]
            blocks += _page_blocks(lines, tables, page_no)

    if not had_text:
        raise PdfNoTextLayer("в pdf нет текстового слоя: похоже на скан, нужно распознавание")
    return blocks


def _page_blocks(lines: list[dict], tables: list[tuple[float, list[list[str]]]], page: int):
    from_tables = {
        " ".join(cell for cell in row if cell)
        for _top, rows in tables
        for row in rows
    }

    blocks: list[Block] = []
    section = ""
    buffer: list[str] = []
    pending = sorted(tables, key=lambda item: item[0])

    def flush() -> None:
        if buffer:
            blocks.append(Block("text", "\n".join(buffer), page, section=section))
            buffer.clear()

    for line in lines:
        while pending and pending[0][0] <= line["top"]:
            _top, rows = pending.pop(0)
            flush()
            blocks.append(Block("table", table_to_text(rows), page, section=section, rows=rows))
        text = line["text"].strip()
        if not text or text in from_tables:
            continue
        if looks_like_heading(text):
            flush()
            section = text
        buffer.append(text)
    flush()

    for _top, rows in pending:
        blocks.append(Block("table", table_to_text(rows), page, section=section, rows=rows))
    return blocks
