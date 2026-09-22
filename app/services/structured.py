from pydantic import ValidationError

from app.agents.prompts import fixer_agent, generator_agent
from app.core.config import settings
from app.core.logging import get_logger
from app.llm.client import run_agent
from app.schemas.cards import CardDraft
from app.services.json_utils import LLMJsonError, parse_llm_json

log = get_logger(__name__)

MAX_FIX_ATTEMPTS = settings.card_fix_attempts


class CardValidationError(Exception):
    pass


def _to_card(answer: object) -> CardDraft:
    if isinstance(answer, CardDraft):
        return answer
    return CardDraft.model_validate(parse_llm_json(answer))


def _broken_field(error: ValidationError) -> str:
    problems = error.errors()
    if len(problems) != 1:
        return ""
    location = problems[0].get("loc") or ()
    return str(location[0]) if len(location) == 1 else ""


def _fix_field_prompt(draft: dict, field: str, error: Exception) -> str:
    import json

    return (
        f"В черновике карточки поле {field!r} не прошло проверку:\n{error}\n\n"
        "Текущий черновик:\n" + json.dumps(draft, ensure_ascii=False, indent=2) + "\n\n"
        f"Исправь только поле {field!r}, остальные верни без изменений. "
        "Ответ — полный JSON карточки."
    )


def _repair_prompt(previous: str, error: Exception) -> str:
    return (
        "Твой прошлый ответ не прошёл проверку. Ошибка:\n"
        f"{error}\n\n"
        "Исправь её и верни строго валидный JSON карточки по тому же контракту.\n"
        "Исходный запрос:\n" + previous
    )


async def validate_or_retry(prompt: str, feedback_prefix: str = "") -> CardDraft:
    current = feedback_prefix + prompt
    agent = generator_agent
    last_error: Exception | None = None

    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        answer = await run_agent(agent, current)
        try:
            return _to_card(answer)
        except LLMJsonError as exc:
            last_error = exc
            log.warning("card_invalid", attempt=attempt + 1, error=str(exc)[:300])
            current, agent = _repair_prompt(current, exc), generator_agent
        except ValidationError as exc:
            last_error = exc
            field = _broken_field(exc)
            raw = _raw_or_none(answer)
            if field and raw is not None:
                log.warning("card_field_invalid", attempt=attempt + 1, field=field)
                current, agent = _fix_field_prompt(raw, field, exc), fixer_agent
            else:
                log.warning("card_invalid", attempt=attempt + 1, error=str(exc)[:300])
                current, agent = _repair_prompt(current, exc), generator_agent

    raise CardValidationError(f"карточка не прошла проверку контракта: {last_error}")


def _raw_or_none(answer: object) -> dict | None:
    try:
        return parse_llm_json(answer)
    except LLMJsonError:
        return None


async def regenerate_field(draft: CardDraft, field: str, error: str) -> CardDraft:
    prompt = (
        f"В черновике карточки поле {field!r} не прошло проверку:\n{error}\n\n"
        "Текущий черновик:\n" + draft.model_dump_json(indent=2) + "\n\n"
        f"Перегенерируй только поле {field!r}, остальные поля верни без изменений. "
        "Ответ — полный JSON карточки."
    )
    log.info("regenerate_field", field=field)
    return _to_card(await run_agent(fixer_agent, prompt))


def confidence_gate(draft: CardDraft) -> str:
    return "done" if draft.confidence >= settings.confidence_threshold else "needs_review"
