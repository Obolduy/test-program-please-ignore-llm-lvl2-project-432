from agents import Agent, AgentOutputSchema, ModelSettings
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.json_utils import parse_llm_json


class JudgeVerdict(BaseModel):
    faithfulness: float = Field(
        ge=0.0, le=1.0, description="Доля утверждений карточки, подтверждённых контекстом"
    )
    reasons: list[str] = Field(default_factory=list)


def judge_instructions() -> str:
    return (
        "Ты строгий оценщик карточек товара. Тебе дают КОНТЕКСТ — фрагменты документов "
        "— и КАРТОЧКУ. Оцени, какая доля утверждений карточки (характеристики, выгоды, "
        "описание) подтверждается контекстом.\n"
        'Верни только JSON: {"faithfulness": <число от 0 до 1>, "reasons": ["..."]}.\n'
        "Выдуманное значение снижает оценку. Никакого markdown."
    )


judge_agent = Agent(
    name="Judge",
    instructions=judge_instructions(),
    model=settings.llm_model_cheap,
    model_settings=ModelSettings(max_tokens=4096, temperature=0.1),
    output_type=AgentOutputSchema(JudgeVerdict, strict_json_schema=False),
)


async def judge_faithfulness(context: str, card_json: str) -> JudgeVerdict:
    from app.llm.client import run_agent

    answer = await run_agent(
        judge_agent, "КОНТЕКСТ:\n" + context + "\n\nКАРТОЧКА:\n" + card_json
    )
    if isinstance(answer, JudgeVerdict):
        return answer
    return JudgeVerdict.model_validate(parse_llm_json(answer))
