import asyncio
import json

import pytest
from pydantic import ValidationError

from app.schemas.cards import CardDraft, Seo, SourceRef
from app.services import structured


def _card(**overrides) -> dict:
    card = {
        "title": "МиксерПро 800 — блендер 800 Вт",
        "description": "Погружной блендер с металлической ножкой.",
        "characteristics": {"Мощность": "800 Вт"},
        "benefits": ["Металлическая ножка"],
        "seo": {"title": "Блендер МиксерПро 800", "description": "Мощный", "keywords": ["блендер"]},
        "sources": [{"chunk_id": "c1", "doc_id": "d1", "page": 3, "score": 0.9}],
        "missing_fields": ["Гарантия"],
        "confidence": 0.8,
    }
    card.update(overrides)
    return card


def test_title_longer_than_limit_is_rejected():
    with pytest.raises(ValidationError, match="60"):
        CardDraft.model_validate(_card(title="А" * 61))


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_confidence_outside_range_is_rejected(value):
    with pytest.raises(ValidationError):
        CardDraft.model_validate(_card(confidence=value))


def test_characteristic_without_value_does_not_reach_the_card():
    card = CardDraft.model_validate(
        _card(characteristics={"Мощность": "800 Вт", "Цвет": "   "})
    )
    assert list(card.characteristics) == ["Мощность"]


def test_field_cannot_be_known_and_missing_at_once():
    with pytest.raises(ValidationError, match="одновременно"):
        CardDraft.model_validate(
            _card(characteristics={"Мощность": "800 Вт"}, missing_fields=["Мощность"])
        )


def test_optional_blocks_have_sane_defaults():
    assert Seo().title == "" and Seo().keywords == []
    ref = SourceRef(chunk_id="c1")
    assert ref.doc_id == "" and ref.page is None and ref.score is None


@pytest.fixture
def scripted_llm(monkeypatch):
    script: list = []
    prompts: list[str] = []

    async def fake_run(agent, prompt):
        import json

        prompts.append(prompt)
        answer = script[len(prompts) - 1]
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)

    monkeypatch.setattr(structured, "run_agent", fake_run)
    return {"script": script, "prompts": prompts}


def test_valid_answer_needs_one_call(scripted_llm):
    scripted_llm["script"].append(_card())
    card = asyncio.run(structured.validate_or_retry("Факты..."))
    assert card.confidence == 0.8
    assert len(scripted_llm["prompts"]) == 1


def test_invalid_answer_goes_back_with_the_error_text(scripted_llm):
    scripted_llm["script"] += [_card(title="А" * 80), _card()]
    card = asyncio.run(structured.validate_or_retry("Факты..."))
    assert len(scripted_llm["prompts"]) == 2
    assert "60" in scripted_llm["prompts"][1]
    assert card.title.startswith("МиксерПро")


def test_too_long_title_goes_to_the_fixer_not_full_regeneration(monkeypatch):
    """Сломано одно поле — чиним поле, описание не перегенерируется."""
    asked: list[str] = []
    answers = [json.dumps(_card(title="А" * 80)), json.dumps(_card())]

    async def fake_run(agent, prompt):
        asked.append(agent.name)
        return answers[len(asked) - 1]

    monkeypatch.setattr(structured, "run_agent", fake_run)
    card = asyncio.run(structured.validate_or_retry("Факты..."))

    assert asked == ["Generator", "Fixer"]
    assert card.title.startswith("МиксерПро")


def test_unparsable_answer_is_also_healed(scripted_llm):
    scripted_llm["script"] += ["я не могу выполнить запрос", _card()]
    assert asyncio.run(structured.validate_or_retry("Факты...")).confidence == 0.8


def test_healing_gives_up_instead_of_looping(scripted_llm):
    bad = _card(title="А" * 80)
    scripted_llm["script"] += [bad] * (structured.MAX_FIX_ATTEMPTS + 1)
    with pytest.raises(structured.CardValidationError):
        asyncio.run(structured.validate_or_retry("Факты..."))
    assert len(scripted_llm["prompts"]) == structured.MAX_FIX_ATTEMPTS + 1


def test_regenerate_field_touches_only_the_broken_field(monkeypatch):
    original = CardDraft.model_validate(_card())
    fixed = CardDraft.model_validate(_card(title="Короткий заголовок"))
    seen: list[str] = []

    async def fake_run(agent, prompt):
        seen.append(prompt)
        return fixed.model_dump_json()

    monkeypatch.setattr(structured, "run_agent", fake_run)
    result = asyncio.run(
        structured.regenerate_field(original, "title", "заголовок длиннее 60 символов")
    )
    assert "title" in seen[0]
    assert original.model_dump_json(indent=2) in seen[0]
    assert result.title == "Короткий заголовок"
    assert result.description == original.description


@pytest.mark.parametrize(
    ("confidence", "expected"), [(0.3, "needs_review"), (0.87, "done"), (0.5, "done")]
)
def test_confidence_gate_sends_doubtful_cards_to_a_human(confidence, expected):
    card = CardDraft.model_validate(_card(confidence=confidence))
    assert structured.confidence_gate(card) == expected
