import asyncio
import random
import time

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 8.0
JITTER_SHARE = 0.25

_client_loop: asyncio.AbstractEventLoop | None = None


def setup_llm() -> None:
    global _client_loop
    loop = asyncio.get_running_loop()
    if _client_loop is loop:
        return
    set_default_openai_client(
        AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_s,
        )
    )
    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)
    _client_loop = loop


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _backoff(attempt: int) -> float:
    delay = min(BACKOFF_BASE_S * 2**attempt, BACKOFF_CAP_S)
    return delay * (1 + random.random() * JITTER_SHARE)


async def run_agent(agent: Agent, prompt: str):
    setup_llm()
    attempts = settings.llm_max_retries
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, prompt), timeout=settings.llm_timeout_s
            )
            _account(agent, result, time.monotonic() - started)
            return result.final_output
        except Exception as exc:
            if attempt == attempts or not _retryable(exc):
                log.error("llm_call_failed", agent=agent.name, attempt=attempt, error=repr(exc))
                raise
            delay = _backoff(attempt)
            log.warning(
                "llm_call_retry",
                agent=agent.name,
                attempt=attempt,
                delay_s=round(delay, 2),
                error=repr(exc),
            )
            await asyncio.sleep(delay)


def _usage(result) -> tuple[int | None, int | None]:
    responses = getattr(result, "raw_responses", None) or []
    usage = getattr(responses[-1], "usage", None) if responses else None
    if usage is None:
        return None, None
    prompt_tokens = getattr(usage, "input_tokens", None)
    completion_tokens = getattr(usage, "output_tokens", None)
    return prompt_tokens, completion_tokens


def _account(agent: Agent, result, elapsed: float) -> None:
    import structlog

    from app.core import db
    from app.llm.cost import calculate_cost
    from app.repositories import llm_calls as calls_repo

    model = getattr(agent, "model", "") or ""
    prompt_tokens, completion_tokens = _usage(result)
    cost = calculate_cost(model, prompt_tokens or 0, completion_tokens or 0)
    latency_ms = int(elapsed * 1000)
    job_id = (structlog.contextvars.get_contextvars() or {}).get("job_id")

    log.info(
        "llm_call",
        agent=agent.name,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=str(cost),
        latency_ms=latency_ms,
    )
    try:
        with db.connection() as conn:
            calls_repo.insert_call(
                conn,
                job_id=job_id,
                agent=agent.name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )
    except Exception as exc:
        log.warning("llm_call_accounting_failed", error=repr(exc))
