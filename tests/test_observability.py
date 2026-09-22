import asyncio
import os
from decimal import Decimal

import pytest

from app.core.config import settings
from app.llm.cost import calculate_cost
from evals import judge
from evals.metrics import citation_hit, field_accuracy, normalize_value


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setitem(settings.llm_prices, "дорогая", {"input": 3.0, "output": 15.0})
    monkeypatch.setitem(settings.llm_prices, "дешёвая", {"input": 0.15, "output": 0.6})


def test_cost_is_counted_exactly_not_in_floats(priced):
    cost = calculate_cost("дорогая", prompt_tokens=1000, completion_tokens=500)
    assert isinstance(cost, Decimal)
    assert cost == Decimal("0.010500")


def test_cheap_model_is_cheaper_on_the_same_spend(priced):
    spend = {"prompt_tokens": 2000, "completion_tokens": 1000}
    assert calculate_cost("дешёвая", **spend) < calculate_cost("дорогая", **spend)


def test_unknown_model_falls_back_to_default_prices():
    assert calculate_cost("нет-такой-модели", 1000, 1000) == Decimal("0.000000")


def test_zero_spend_costs_nothing(priced):
    assert calculate_cost("дорогая", 0, 0) == Decimal("0.000000")


@pytest.mark.parametrize("value", ["800 Вт", "800 вт", "800 Вт.", " 800 Вт ", "800вт"])
def test_same_value_written_differently_is_the_same_value(value):
    assert normalize_value(value) == normalize_value("800 Вт")


def test_field_accuracy_counts_matches_after_normalisation():
    golden = {"Мощность": "800 Вт", "Гарантия": "24 месяца"}
    assert field_accuracy({"Мощность": "800 вт.", "Гарантия": "24 месяца"}, golden) == 1.0
    assert field_accuracy({"Мощность": "800 Вт"}, golden) == 0.5
    assert field_accuracy({"Мощность": "1200 Вт"}, golden) == 0.0


def test_field_accuracy_without_expectations_is_perfect():
    assert field_accuracy({}, {}) == 1.0


def test_citation_hit_checks_the_claimed_chunk_really_contains_it():
    chunks = {"c1": {"text": "Мощность: 800 Вт"}, "c2": {"text": "Цвет графитовый"}}
    probes = {"Мощность": {"text_contains": "800 Вт"}}
    assert citation_hit([{"chunk_id": "c1"}], probes, chunks) == 1.0
    assert citation_hit([{"chunk_id": "c2"}], probes, chunks) == 0.0
    assert citation_hit([{"chunk_id": "нет"}], probes, chunks) == 0.0


def test_judge_asks_the_cheap_model():
    assert judge.judge_agent.model == settings.llm_model_cheap


def test_judge_returns_a_structured_verdict(monkeypatch):
    seen: list[str] = []

    async def fake_run(agent, prompt):
        seen.append(prompt)
        return '{"faithfulness": 0.75, "reasons": ["цвет в контексте не подтверждён"]}'

    monkeypatch.setattr("app.llm.client.run_agent", fake_run)
    verdict = asyncio.run(judge.judge_faithfulness("[c1 | ф.pdf]\nМощность 800 Вт", '{"title": "x"}'))
    assert verdict.faithfulness == 0.75
    assert verdict.reasons
    assert "КОНТЕКСТ:" in seen[0] and "КАРТОЧКА:" in seen[0]


def test_judge_rejects_a_score_outside_the_range(monkeypatch):
    async def fake_run(agent, prompt):
        return '{"faithfulness": 1.4}'

    monkeypatch.setattr("app.llm.client.run_agent", fake_run)
    with pytest.raises(Exception, match="faithfulness"):
        asyncio.run(judge.judge_faithfulness("контекст", "{}"))


@pytest.mark.skipif(os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1")
def test_job_cost_is_one_query_by_job_id():
    from app.core import db
    from app.repositories import llm_calls as calls_repo

    job_id = "тест-стоимость"
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM llm_calls WHERE job_id = %s", (job_id,))
        for model, cost in (("основная", Decimal("0.01")), ("дешёвая", Decimal("0.001"))):
            calls_repo.insert_call(
                conn, job_id=job_id, agent="A", model=model,
                prompt_tokens=100, completion_tokens=50, cost=cost, latency_ms=120,
            )
        spend = calls_repo.job_cost(conn, job_id)
        models = {row["model"] for row in calls_repo.by_model(conn)}
        with conn.cursor() as cur:
            cur.execute("DELETE FROM llm_calls WHERE job_id = %s", (job_id,))

    assert spend["calls"] == 2
    assert Decimal(spend["cost"]) == Decimal("0.011")
    assert spend["prompt_tokens"] == 200
    assert {"основная", "дешёвая"} <= models
