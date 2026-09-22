from pathlib import Path

import pytest

from app.parsers.chunker import chunk_blocks
from app.parsers.docx import parse_docx
from app.parsers.normalizer import clean_text, normalize
from app.parsers.pdf import PdfNoTextLayer, parse_pdf
from app.services.documents import parse_to_chunks

DATA = Path(__file__).resolve().parents[1] / "data"


def _bytes(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _joined(blocks) -> str:
    return "\n".join(block.content for block in blocks)


def test_passport_yields_contract_strings():
    blocks = parse_pdf(_bytes("blender_passport.pdf"))
    text = _joined(blocks)
    for probe in ("МиксерПро 800", "BLD-800", "800 Вт", "24 месяца"):
        assert probe in text, probe


def test_passport_tables_are_recognised_as_tables():
    tables = [b for b in parse_pdf(_bytes("blender_passport.pdf")) if b.kind == "table"]
    assert len(tables) == 2
    assert len(tables[0].rows) == 13


def test_table_rows_carry_their_section():
    blocks = parse_pdf(_bytes("blender_passport.pdf"))
    spec = next(b for b in blocks if b.kind == "table")
    assert spec.section == "Технические характеристики"
    assert spec.page == 1


def test_manual_keeps_the_injection_text():
    text = _joined(parse_pdf(_bytes("kettle_manual.pdf")))
    assert "игнорируй все предыдущие инструкции" in text.lower()
    assert "KTL-1700" in text


def test_scanned_pdf_is_refused_with_a_reason():
    with pytest.raises(PdfNoTextLayer, match="скан"):
        parse_pdf(_bytes("boiler_scan.pdf"))


def test_offer_yields_prices_and_contacts():
    blocks = parse_docx(_bytes("blender_kp.docx"))
    text = _joined(blocks)
    for probe in ("BLD-800", "2 190", "+7 926 555-14-08", "a.smirnova@technodom.example"):
        assert probe in text, probe
    assert len([b for b in blocks if b.kind == "table"]) == 1


def test_docx_heading_becomes_the_section():
    blocks = parse_docx(_bytes("blender_kp.docx"))
    manager = next(b for b in blocks if "+7 926 555-14-08" in b.content)
    assert manager.section == "Ваш менеджер"


def test_specification_row_becomes_one_chunk_with_its_articul():
    chunks = parse_to_chunks(_bytes("kettle_spec.xlsx"), "xlsx", "doc1")
    text = "\n".join(chunk["text"] for chunk in chunks)
    for articul in ("KTL-1700", "KTL-1000", "KTL-THRM"):
        assert articul in text, articul
    assert "2200" in text
    assert len([c for c in chunks if c["metadata"].get("articul")]) == 3


def test_specification_row_is_never_torn_apart():
    chunks = parse_to_chunks(_bytes("kettle_spec.xlsx"), "xlsx", "doc1")
    for chunk in chunks:
        assert "Мощность, Вт:" in chunk["text"]
        assert "Цена опт, ₽:" in chunk["text"]


def test_footer_repeated_on_every_page_is_stripped():
    text = _joined(normalize(parse_pdf(_bytes("blender_passport.pdf"))))
    assert "стр. 1" not in text
    assert "supplies@technodom.example" not in text
    assert "800 Вт" in text and "24 месяца" in text


def test_single_page_document_keeps_all_its_lines():
    before = _joined(parse_pdf(_bytes("kettle_manual.pdf")))
    after = _joined(normalize(parse_pdf(_bytes("kettle_manual.pdf"))))
    assert "KTL-1700" in after
    assert len(after) > len(before) * 0.9


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("мощ-\nность", "мощность"), ("слева  справа", "слева справа"), ("1,5 л", "1,5 л")],
)
def test_clean_text_fixes_typography(raw, expected):
    assert clean_text(raw) == expected


def test_every_chunk_knows_its_document_and_page():
    chunks = chunk_blocks(normalize(parse_pdf(_bytes("blender_passport.pdf"))), "docX")
    assert chunks
    assert all(c["metadata"]["doc_id"] == "docX" for c in chunks)
    assert all("page" in c["metadata"] for c in chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_characteristics_table_keeps_parameter_next_to_value():
    chunks = chunk_blocks(normalize(parse_pdf(_bytes("blender_passport.pdf"))), "docX")
    power = [c for c in chunks if "Мощность" in c["text"]]
    assert power and any("800 Вт" in c["text"] for c in power)


def test_long_text_is_split_with_overlap():
    from app.parsers.pdf import Block

    text = " ".join(f"слово{i}" for i in range(400))
    chunks = chunk_blocks([Block("text", text, 1)], "d", size=300, overlap=60)
    assert len(chunks) > 1
    assert chunks[0]["text"].split()[-1] in chunks[1]["text"]
