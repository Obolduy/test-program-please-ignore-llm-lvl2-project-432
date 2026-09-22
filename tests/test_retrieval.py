import json
import math
import os

import pytest

from app.core import db
from app.repositories import chunks as chunks_repo

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)

DOC_ID = "тест-поиск"
DIM = 768


def _unit(head: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in head))
    return [value / length for value in head] + [0.0] * (DIM - len(head))


BLENDER = _unit([1, 0])
KETTLE = _unit([0, 1])
BOTH = _unit([1, 1])


@pytest.fixture
def indexed_chunks(monkeypatch):
    rows = [
        ("тчанк1", 0, "Мощность блендера 800 Вт", BLENDER),
        ("тчанк2", 1, "Чайник 2200 Вт, объём 1.7 л", KETTLE),
        ("тчанк3", 2, "Гарантия 24 месяца на любую модель", BOTH),
    ]
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (DOC_ID,))
            cur.execute(
                "INSERT INTO documents (id, filename, content_hash, kind, status) "
                "VALUES (%s, 'проверка.pdf', %s, 'pdf', 'indexed')",
                (DOC_ID, "хэш-" + DOC_ID),
            )
            for chunk_id, ordinal, text, vector in rows:
                cur.execute(
                    "INSERT INTO chunks (id, doc_id, ordinal, text, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                    (
                        chunk_id,
                        DOC_ID,
                        ordinal,
                        text,
                        json.dumps({"doc_id": DOC_ID, "page": 1}),
                        chunks_repo.vector_literal(vector),
                    ),
                )

        monkeypatch.setattr(
            chunks_repo,
            "embed_query",
            lambda text: BLENDER if "блендер" in text.lower() else KETTLE,
        )
        yield conn
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (DOC_ID,))


def test_vector_search_finds_the_meaning(indexed_chunks):
    found = chunks_repo.search_vector(indexed_chunks, "мощность блендера", top_k=3)
    assert found, "пусто — проверьте порог и векторы"
    assert found[0]["chunk_id"] == "тчанк1"
    assert found[0]["score"] >= 0.9


def test_threshold_cuts_everything_but_a_close_match(indexed_chunks):
    found = chunks_repo.search_vector(
        indexed_chunks, "мощность блендера", top_k=5, threshold=0.99
    )
    ids = [item["chunk_id"] for item in found]
    assert "тчанк1" in ids and "тчанк2" not in ids


def test_word_search_finds_exact_words_the_vector_misses(indexed_chunks):
    by_vector = chunks_repo.search_vector(indexed_chunks, "гарантия", top_k=5)
    by_words = chunks_repo.search_fts(indexed_chunks, "гарантия", top_k=50)
    assert any(item["chunk_id"] == "тчанк3" for item in by_words)
    assert by_vector and by_vector[0]["chunk_id"] != "тчанк3"


def test_hybrid_puts_the_double_hit_on_top(indexed_chunks):
    found = chunks_repo.search_hybrid(indexed_chunks, "мощность блендера", top_k=3)
    ids = [item["chunk_id"] for item in found]
    assert found[0]["chunk_id"] == "тчанк1"
    assert "тчанк1" in ids


def test_hybrid_returns_union_of_both_lists(indexed_chunks):
    by_vector = {i["chunk_id"] for i in chunks_repo.search_vector(indexed_chunks, "чайник", top_k=3)}
    by_words = {i["chunk_id"] for i in chunks_repo.search_fts(indexed_chunks, "чайник", top_k=3)}
    hybrid = {i["chunk_id"] for i in chunks_repo.search_hybrid(indexed_chunks, "чайник", top_k=9)}
    assert by_vector | by_words <= hybrid


def test_document_filter_excludes_everything_else(indexed_chunks):
    assert chunks_repo.search_vector(
        indexed_chunks, "мощность блендера", top_k=3, doc_ids=["другой-документ"]
    ) == []


def test_chunks_by_ids_returns_them_keyed(indexed_chunks):
    found = chunks_repo.get_chunks_by_ids(indexed_chunks, ["тчанк1", "нет-такого"])
    assert set(found) == {"тчанк1"}
    assert found["тчанк1"]["text"].startswith("Мощность")


def test_reindex_does_nothing_on_a_second_run(indexed_chunks):
    from app.rag import reindex

    assert chunks_repo.chunks_without_embedding(indexed_chunks, doc_id=DOC_ID) == []
    assert reindex.index_pending(indexed_chunks, DOC_ID) == 0
