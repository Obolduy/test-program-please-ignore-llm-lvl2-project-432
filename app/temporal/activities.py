import json
from pathlib import Path

import structlog
from temporalio import activity

from app.core import db
from app.core.logging import get_logger
from app.repositories import documents as docs_repo
from app.repositories import jobs as jobs_repo
from app.schemas.cards import CardDraft, SupplierFacts
from app.services import documents as docs_service
from app.services import pipeline

log = get_logger(__name__)


@activity.defn
async def extract_activity(supplier_text: str) -> str:
    facts = await pipeline.extract(supplier_text)
    return facts.model_dump_json()


@activity.defn
async def generate_activity(facts_json: str, feedback_json: str | None = None) -> str:
    facts = SupplierFacts.model_validate_json(facts_json)
    feedback = json.loads(feedback_json) if feedback_json else None
    draft = await pipeline.generate(facts, feedback)
    return draft.model_dump_json()


@activity.defn
async def critique_activity(facts_json: str, draft_json: str) -> str:
    facts = SupplierFacts.model_validate_json(facts_json)
    draft = CardDraft.model_validate_json(draft_json)
    report = await pipeline.critique(facts, draft)
    return report.model_dump_json()


@activity.defn
def set_job_status_activity(
    job_id: str,
    status: str,
    draft_json: str | None = None,
    error: str | None = None,
    guard_json: str | None = None,
) -> None:
    with db.connection() as conn:
        jobs_repo.set_status(
            conn,
            job_id,
            status,
            result=CardDraft.model_validate_json(draft_json) if draft_json else None,
            guard=json.loads(guard_json) if guard_json else None,
            error=error,
            bump_attempts=status == "generating",
        )


@activity.defn
def parse_document_activity(doc_id: str, path: str, kind: str) -> int:
    structlog.contextvars.bind_contextvars(doc_id=doc_id)
    file = Path(path)
    try:
        with db.connection() as conn:
            return docs_service.ingest(conn, doc_id, file.read_bytes(), kind)
    finally:
        file.unlink(missing_ok=True)


@activity.defn
def rag_card_activity(job_id: str, document_ids: list[str], product_hint: str = "") -> str:
    import asyncio

    from app.services import rag_pipeline

    structlog.contextvars.bind_contextvars(job_id=job_id)
    query = product_hint or _document_title(document_ids)
    try:
        draft, attempts, _verdict, status, guard = asyncio.run(
            rag_pipeline.run_rag_pipeline(
                query,
                document_ids or None,
                on_stage=lambda stage: _publish(job_id, stage, bump=stage == "generating"),
            )
        )
        if draft is None:
            raise RuntimeError("карточка не собралась")
        log.info(
            "rag_card_ready", job_id=job_id, status=status, attempts=attempts,
            guard=guard.as_dict(),
        )
        return json.dumps(
            {"card": draft.model_dump(mode="json"), "guard": guard.as_dict(), "status": status},
            ensure_ascii=False,
        )
    except Exception as exc:
        _publish(job_id, "failed", error=repr(exc))
        log.error("rag_job_failed", job_id=job_id, error=repr(exc))
        raise


def _document_title(document_ids: list[str]) -> str:
    """Без подсказки ищем по имени первого выбранного документа."""
    if not document_ids:
        return ""
    with db.connection() as conn:
        document = docs_repo.get_document(conn, document_ids[0])
    return Path(document["filename"]).stem.replace("_", " ") if document else ""


def _publish(
    job_id: str, status: str, *, draft=None, guard=None, error=None, bump: bool = False
) -> None:
    with db.connection() as conn:
        jobs_repo.set_status(
            conn, job_id, status, result=draft, guard=guard, error=error, bump_attempts=bump
        )
