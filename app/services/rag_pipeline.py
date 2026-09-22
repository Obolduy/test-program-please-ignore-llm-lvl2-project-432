from collections.abc import Callable

from pydantic import ValidationError

from app.agents.prompts import context_critic_agent, context_generator_agent
from app.core import db
from app.core.config import settings
from app.core.logging import get_logger
from app.guardrails import GuardReport, guard_context, guard_output
from app.llm.client import run_agent
from app.rag.context import INSTRUCTION, build_context, context_chunk_ids
from app.rag.retrieval import search
from app.repositories import chunks as chunks_repo
from app.schemas.cards import CardDraft, CritiqueReport
from app.services.json_utils import LLMJsonError, parse_llm_json
from app.services.structured import MAX_FIX_ATTEMPTS, confidence_gate

log = get_logger(__name__)

DEFAULT_QUERY = "характеристики товара"


class SourceValidationError(Exception):
    pass


async def retrieve_context_async(
    query: str, doc_ids: list[str] | None = None
) -> tuple[str, GuardReport]:
    chunks = search(query, mode="hybrid", doc_ids=doc_ids, top_k=settings.retrieval_top_k)
    safe, report = await guard_context(chunks)
    return build_context(safe), report


def _to_card(answer: object) -> CardDraft:
    if isinstance(answer, CardDraft):
        return answer
    return CardDraft.model_validate(parse_llm_json(answer))


def validate_sources(draft: CardDraft, allowed: set[str]) -> None:
    if not draft.sources:
        return
    claimed = {ref.chunk_id for ref in draft.sources}

    unseen = claimed - allowed
    if unseen:
        raise SourceValidationError(
            f"источники, которых не было в контексте: {sorted(unseen)}"
        )

    with db.connection() as conn:
        existing = set(chunks_repo.get_chunks_by_ids(conn, sorted(claimed)))
    missing = claimed - existing
    if missing:
        raise SourceValidationError(f"источники не существуют в базе: {sorted(missing)}")


async def generate_from_context(context: str, feedback: list[str] | None = None) -> CardDraft:
    allowed = context_chunk_ids(context)
    prefix = ""
    if feedback:
        prefix = (
            "Замечания проверяющего, учти их:\n"
            + "\n".join(f"- {issue}" for issue in feedback)
            + "\n\n"
        )
    current = prefix + INSTRUCTION + "\nКОНТЕКСТ:\n" + context
    last_error: Exception | None = None

    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        answer = await run_agent(context_generator_agent, current)
        try:
            draft = _to_card(answer)
            validate_sources(draft, allowed)
            return draft
        except (LLMJsonError, ValidationError, SourceValidationError) as exc:
            last_error = exc
            log.warning("rag_card_rejected", attempt=attempt + 1, error=str(exc)[:300])
            current = (
                f"Твой прошлый ответ отклонён. Причина:\n{exc}\n\n"
                f"Разрешённые chunk_id для sources: {sorted(allowed)}.\n"
                "Исправь и верни валидный JSON карточки.\n"
                "Исходный запрос:\n" + current
            )
    raise SourceValidationError(f"карточку не удалось принять: {last_error}")


async def critique_with_context(context: str, draft: CardDraft) -> CritiqueReport:
    prompt = (
        "КОНТЕКСТ:\n" + context + "\n\nЧерновик карточки:\n" + draft.model_dump_json(indent=2)
    )
    answer = await run_agent(context_critic_agent, prompt)
    if isinstance(answer, CritiqueReport):
        return answer
    return CritiqueReport.model_validate(parse_llm_json(answer))


async def run_rag_pipeline(
    query: str,
    doc_ids: list[str] | None = None,
    max_attempts: int = 3,
    context: str | None = None,
    on_stage: Callable[[str], None] | None = None,
):
    announce = on_stage or (lambda _stage: None)
    guard_report = GuardReport()
    if context is None:
        announce("retrieving")
        context, guard_report = await retrieve_context_async(query or DEFAULT_QUERY, doc_ids)
    feedback: list[str] = []
    draft: CardDraft | None = None
    attempts = 0
    verdict = "rejected"

    while attempts < max_attempts:
        attempts += 1
        announce("generating")
        draft = await generate_from_context(context, feedback or None)
        announce("critiquing")
        report = await critique_with_context(context, draft)
        if report.verdict == "approve":
            verdict = "approved"
            break
        feedback = report.issues
        log.info("rag_rework", attempt=attempts, issues=report.issues)

    if verdict == "approved" and draft is not None:
        cleaned, issues = guard_output(draft.model_dump_json())
        if issues:
            guard_report.output_issues = issues
            log.warning("guard_output_issues", issues=issues)
            draft = CardDraft.model_validate_json(cleaned)

    status = "rejected"
    if verdict == "approved" and draft is not None:
        status = confidence_gate(draft)
        if guard_report.needs_review or guard_report.output_issues:
            status = "needs_review"
    return draft, attempts, verdict, status, guard_report
