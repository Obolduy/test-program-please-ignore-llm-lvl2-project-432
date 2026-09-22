import asyncio
import json
import os

import pytest

from app.core import db
from app.rag.context import build_context, context_chunk_ids
from app.services import rag_pipeline

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)

DOC_ID = "ragdoc1"
CHUNKS = {
    "ragc1": "Блендер МиксерПро 800. Мощность: 800 Вт. Скоростей: 6. Артикул: BLD-800.",
    "ragc2": "Гарантия 24 месяца. Цвет графитовый. Комплект: венчик, стакан 1,5 л.",
}


@pytest.fixture(scope="module")
def indexed_document():
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (DOC_ID,))
            cur.execute(
                "INSERT INTO documents (id, filename, content_hash, kind, status) "
                "VALUES (%s, 'блендер.pdf', 'хэш-rag', 'pdf', 'indexed')",
                (DOC_ID,),
            )
            for ordinal, (chunk_id, text) in enumerate(CHUNKS.items()):
                cur.execute(
                    "INSERT INTO chunks (id, doc_id, ordinal, text, metadata) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (chunk_id, DOC_ID, ordinal, text,
                     json.dumps({"doc_id": DOC_ID, "page": 1})),
                )
        yield conn
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (DOC_ID,))


def _chunk(chunk_id: str, **metadata) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": CHUNKS.get(chunk_id, "текст " + chunk_id),
        "metadata": {"doc_id": DOC_ID, "page": 1, **metadata},
        "filename": "блендер.pdf",
    }


def test_every_chunk_in_context_is_identifiable():
    context = build_context([_chunk("ragc1", page=2, section="Характеристики")])
    assert "[ragc1 | блендер.pdf | стр. 2 | Характеристики]" in context
    assert "Мощность: 800 Вт" in context
    assert context_chunk_ids(context) == {"ragc1"}


def test_context_drops_repeats():
    same = [_chunk("ragc1"), _chunk("ragc1"), {**_chunk("ragc9"), "text": CHUNKS["ragc1"]}]
    assert context_chunk_ids(build_context(same)) == {"ragc1"}


def test_context_respects_its_size_limit():
    chunks = [{**_chunk(f"c{i}"), "text": "х" * 4000} for i in range(5)]
    context = build_context(chunks, max_chars=6000)
    assert len(context) < 6200
    assert len(context_chunk_ids(context)) < 5


def _card(chunk_id: str = "ragc1", confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "title": "МиксерПро 800 — блендер 800 Вт",
            "description": "Погружной блендер с металлической ножкой.",
            "characteristics": {"Мощность": "800 Вт"},
            "benefits": ["Металлическая ножка"],
            "seo": {"title": "Блендер", "description": "Мощный", "keywords": ["блендер"]},
            "sources": [{"chunk_id": chunk_id, "page": 1}],
            "missing_fields": [],
            "confidence": confidence,
        },
        ensure_ascii=False,
    )


@pytest.fixture
def fake_model(monkeypatch):

    def install(card_json: str, verdict: str = "approve", context_ids=("ragc1",)):
        context = build_context([_chunk(cid) for cid in context_ids])

        async def fake_retrieve(query, doc_ids=None):
            from app.guardrails import GuardReport

            return context, GuardReport()

        async def fake_run(agent, prompt):
            if agent.name == "Critic":
                return json.dumps({"verdict": verdict, "issues": [], "field": ""})
            return card_json

        monkeypatch.setattr(rag_pipeline, "retrieve_context_async", fake_retrieve)
        monkeypatch.setattr(rag_pipeline, "run_agent", fake_run)
        return context

    return install


def test_card_cites_a_chunk_that_really_exists(indexed_document, fake_model):
    fake_model(_card())
    draft, attempts, verdict, status, _guard = asyncio.run(
        rag_pipeline.run_rag_pipeline("блендер", [DOC_ID])
    )
    assert (attempts, verdict, status) == (1, "approved", "done")
    assert draft.sources[0].chunk_id == "ragc1"

    from app.repositories import chunks as chunks_repo

    assert "ragc1" in chunks_repo.get_chunks_by_ids(indexed_document, ["ragc1"])


def test_invented_source_does_not_pass(indexed_document, fake_model):
    fake_model(_card(chunk_id="несуществующий"))
    with pytest.raises(rag_pipeline.SourceValidationError):
        asyncio.run(rag_pipeline.run_rag_pipeline("блендер", [DOC_ID]))


def test_existing_chunk_that_was_not_in_context_is_also_invented(indexed_document, fake_model):
    fake_model(_card(chunk_id="ragc2"), context_ids=("ragc1",))
    with pytest.raises(rag_pipeline.SourceValidationError, match="не было в контексте"):
        asyncio.run(rag_pipeline.run_rag_pipeline("блендер", [DOC_ID]))


def test_pipeline_announces_every_stage(indexed_document, fake_model):
    """Состояния пишутся по ходу, иначе долгая задача выглядит зависшей."""
    fake_model(_card())
    seen: list[str] = []
    asyncio.run(
        rag_pipeline.run_rag_pipeline("блендер", [DOC_ID], on_stage=seen.append)
    )
    assert seen == ["retrieving", "generating", "critiquing"]


def test_low_confidence_sends_the_card_to_a_human(indexed_document, fake_model):
    fake_model(_card(confidence=0.3))
    _draft, _attempts, _verdict, status, _guard = asyncio.run(
        rag_pipeline.run_rag_pipeline("блендер", [DOC_ID])
    )
    assert status == "needs_review"


def test_source_validation_checks_both_conditions(indexed_document):
    from app.schemas.cards import CardDraft

    draft = CardDraft.model_validate_json(_card(chunk_id="ragc2"))
    rag_pipeline.validate_sources(draft, allowed={"ragc2"})
    ghost = CardDraft.model_validate_json(_card(chunk_id="призрак"))
    with pytest.raises(rag_pipeline.SourceValidationError, match="не существуют"):
        rag_pipeline.validate_sources(ghost, allowed={"призрак"})
