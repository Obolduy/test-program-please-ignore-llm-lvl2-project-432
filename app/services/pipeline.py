from pydantic import BaseModel

from app.agents.prompts import critic_agent, extractor_agent
from app.core.logging import get_logger
from app.llm.client import run_agent
from app.schemas.cards import CardDraft, CritiqueReport, SupplierFacts
from app.services.json_utils import parse_llm_json
from app.services.structured import confidence_gate, regenerate_field, validate_or_retry

log = get_logger(__name__)

MAX_ATTEMPTS = 3
FIXABLE_FIELDS = frozenset(CardDraft.model_fields) - {"sources"}


def _as_model(out: object, model: type[BaseModel]) -> BaseModel:
    if isinstance(out, model):
        return out
    return model.model_validate(parse_llm_json(out))


async def extract(supplier_text: str) -> SupplierFacts:
    log.info("stage_extract")
    return _as_model(await run_agent(extractor_agent, supplier_text), SupplierFacts)


async def generate(facts: SupplierFacts, feedback: list[str] | None = None) -> CardDraft:
    prefix = ""
    if feedback:
        prefix = (
            "Замечания проверяющего, учти их:\n"
            + "\n".join(f"- {issue}" for issue in feedback)
            + "\n\n"
        )
    log.info("stage_generate", reworked=bool(feedback))
    prompt = "Факты о товаре:\n" + facts.model_dump_json(indent=2)
    return await validate_or_retry(prompt, feedback_prefix=prefix)


async def critique(facts: SupplierFacts, draft: CardDraft) -> CritiqueReport:
    prompt = (
        "Факты о товаре:\n"
        + facts.model_dump_json(indent=2)
        + "\n\nЧерновик карточки:\n"
        + draft.model_dump_json(indent=2)
    )
    log.info("stage_critique")
    return _as_model(await run_agent(critic_agent, prompt), CritiqueReport)


async def run_pipeline(supplier_text: str, max_attempts: int = MAX_ATTEMPTS):
    facts = await extract(supplier_text)
    feedback: list[str] = []
    draft: CardDraft | None = None
    attempts = 0
    verdict = "rejected"

    broken_field = ""
    while attempts < max_attempts:
        attempts += 1
        if draft is not None and broken_field:
            draft = await regenerate_field(draft, broken_field, "; ".join(feedback))
        else:
            draft = await generate(facts, feedback or None)
        report = await critique(facts, draft)
        if report.verdict == "approve":
            verdict = "approved"
            break
        feedback = report.issues
        broken_field = report.field if report.field in FIXABLE_FIELDS else ""
        log.info(
            "pipeline_rework", attempt=attempts, issues=report.issues, field=broken_field or "все"
        )

    status = confidence_gate(draft) if verdict == "approved" and draft else "rejected"
    return draft, attempts, verdict, status
