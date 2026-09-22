import asyncio

import pytest

from app.llm import client as llm_client
from app.schemas.cards import CardDraft, CritiqueReport, SupplierFacts
from app.services import pipeline, structured
from app.services.json_utils import LLMJsonError, parse_llm_json


def _facts() -> SupplierFacts:
    return SupplierFacts(
        product_name="Блендер погружной «МиксерПро 800»",
        characteristics={"Мощность": "800 Вт", "Питание": "220 В"},
    )


def _draft(title: str = "МиксерПро 800 — блендер 800 Вт") -> CardDraft:
    return CardDraft(
        title=title,
        description="Погружной блендер с металлической ножкой и турбо-режимом.",
        characteristics={"Мощность": "800 Вт"},
        benefits=["Металлическая ножка", "6 скоростей"],
    )


@pytest.fixture
def scripted_llm(monkeypatch):
    script: list = []
    calls: list[str] = []

    async def fake_run(agent, prompt):
        calls.append(prompt)
        answer = script[len(calls) - 1]
        return answer if isinstance(answer, str) else answer.model_dump_json()

    monkeypatch.setattr(pipeline, "run_agent", fake_run)
    monkeypatch.setattr(structured, "run_agent", fake_run)
    return {"script": script, "calls": calls}


def test_extract_survives_markdown_fencing(scripted_llm):
    scripted_llm["script"].append("```json\n" + _facts().model_dump_json() + "\n```")
    facts = asyncio.run(pipeline.extract("текст поставщика"))
    assert facts.characteristics["Мощность"] == "800 Вт"


def test_pipeline_stops_on_first_approve(scripted_llm):
    scripted_llm["script"] += [_facts(), _draft(), CritiqueReport(verdict="approve")]
    draft, attempts, verdict, status = asyncio.run(pipeline.run_pipeline("текст"))
    assert (attempts, verdict, status) == (1, "approved", "done")
    assert draft.title.startswith("МиксерПро")


def test_pipeline_passes_issues_into_next_prompt(scripted_llm):
    scripted_llm["script"] += [
        _facts(),
        _draft(), CritiqueReport(verdict="regenerate", issues=["заголовок длиннее нормы"]),
        _draft(), CritiqueReport(verdict="approve"),
    ]
    _draft_out, attempts, verdict, _status = asyncio.run(pipeline.run_pipeline("текст"))
    assert (attempts, verdict) == (2, "approved")
    assert "заголовок длиннее нормы" in scripted_llm["calls"][3]


def test_single_broken_field_is_fixed_pointwise(monkeypatch):
    agents_asked: list[str] = []
    answers = [
        _facts(),
        _draft(title="Блендер погружной МиксерПро 800 на 800 Вт графит"),
        CritiqueReport(verdict="regenerate", issues=["заголовок длинный"], field="title"),
        _draft(title="МиксерПро 800 — блендер"),
        CritiqueReport(verdict="approve"),
    ]

    async def fake_run(agent, prompt):
        agents_asked.append(agent.name)
        answer = answers[len(agents_asked) - 1]
        return answer if isinstance(answer, str) else answer.model_dump_json()

    monkeypatch.setattr(pipeline, "run_agent", fake_run)
    monkeypatch.setattr(structured, "run_agent", fake_run)

    draft, attempts, verdict, _status = asyncio.run(pipeline.run_pipeline("текст"))
    assert (attempts, verdict) == (2, "approved")
    assert agents_asked == ["Extractor", "Generator", "Critic", "Fixer", "Critic"]
    assert draft.title == "МиксерПро 800 — блендер"


def test_unnamed_field_falls_back_to_full_rework(scripted_llm):
    scripted_llm["script"] += [
        _facts(),
        _draft(), CritiqueReport(verdict="regenerate", issues=["вода", "мало выгод"]),
        _draft(), CritiqueReport(verdict="approve"),
    ]
    _d, attempts, verdict, _s = asyncio.run(pipeline.run_pipeline("текст"))
    assert (attempts, verdict) == (2, "approved")


def test_pipeline_gives_up_after_max_attempts(scripted_llm):
    scripted_llm["script"] += [_facts()] + [
        item
        for _ in range(3)
        for item in (_draft(), CritiqueReport(verdict="regenerate", issues=["вода"]))
    ]
    draft, attempts, verdict, status = asyncio.run(
        pipeline.run_pipeline("текст", max_attempts=3)
    )
    assert (attempts, verdict, status) == (3, "rejected", "rejected")
    assert draft is not None


class _Answer:
    final_output = "ok"


def _status_error(code: int):
    from openai import APIStatusError

    err = APIStatusError.__new__(APIStatusError)
    err.status_code = code
    return err


class _Agent:
    name = "test"


@pytest.fixture(autouse=True)
def no_accounting(monkeypatch):
    monkeypatch.setattr(llm_client, "_account", lambda *args, **kwargs: None)


def test_client_retries_on_too_many_requests(monkeypatch):
    calls = {"n": 0}
    delays: list[float] = []

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _status_error(429)
            return _Answer()

    async def no_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(llm_client, "setup_llm", lambda: None)
    monkeypatch.setattr(llm_client, "Runner", FakeRunner)
    monkeypatch.setattr(llm_client.asyncio, "sleep", no_sleep)

    assert asyncio.run(llm_client.run_agent(_Agent(), "x")) == "ok"
    assert calls["n"] == 2
    assert len(delays) == 1 and delays[0] > 0


def test_client_does_not_retry_bad_request(monkeypatch):
    from openai import APIStatusError

    calls = {"n": 0}

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt):
            calls["n"] += 1
            raise _status_error(400)

    monkeypatch.setattr(llm_client, "setup_llm", lambda: None)
    monkeypatch.setattr(llm_client, "Runner", FakeRunner)

    with pytest.raises(APIStatusError):
        asyncio.run(llm_client.run_agent(_Agent(), "x"))
    assert calls["n"] == 1


def test_retryable_says_no_to_ordinary_errors():
    assert llm_client._retryable(Exception("x")) is False
    assert llm_client._retryable(ValueError("x")) is False
    assert llm_client._retryable(_status_error(503)) is True


def test_backoff_grows_and_is_capped():
    assert llm_client._backoff(1) < llm_client._backoff(5)
    assert llm_client._backoff(20) <= llm_client.BACKOFF_CAP_S * (1 + llm_client.JITTER_SHARE)


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Вот ваша карточка:\n{"a": 1}\nЕсли что — обращайтесь!',
        '```\n{"a": 1}\n```',
    ],
)
def test_parse_llm_json_accepts_dirty_answers(raw):
    assert parse_llm_json(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["", "   ", "Простите, я не могу выполнить запрос", "[1, 2]"])
def test_parse_llm_json_rejects_garbage(raw):
    with pytest.raises(LLMJsonError):
        parse_llm_json(raw)
