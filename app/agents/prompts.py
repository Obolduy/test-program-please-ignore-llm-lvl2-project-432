from agents import Agent, AgentOutputSchema, ModelSettings

from app.core.config import settings
from app.schemas.cards import CardDraft, CritiqueReport, SupplierFacts

TITLE_LIMIT = 60

_SETTINGS = ModelSettings(max_tokens=4096, temperature=0.4)


def extractor_instructions() -> str:
    return (
        "Ты извлекаешь факты. Из текста поставщика собери структурированные данные.\n"
        "Верни только JSON с полями:\n"
        "- product_name (строка): название товара\n"
        "- characteristics (объект): пары ключ-значение, взятые ИЗ ТЕКСТА\n"
        "- missing_fields (массив строк): что важно для карточки, но в тексте "
        "отсутствует — гарантия, цвет, страна-производитель и подобное\n"
        "Ничего не додумывай: нет данных — имя поля идёт в missing_fields.\n"
        "Никакого markdown и пояснений."
    )


def generator_instructions() -> str:
    return (
        "Ты копирайтер маркетплейса. По фактам о товаре собери черновик карточки.\n"
        "Верни только JSON с полями:\n"
        f"- title (строка): заголовок не длиннее {TITLE_LIMIT} символов\n"
        "- description (строка): три-четыре предложения по делу, без воды\n"
        "- characteristics (объект): характеристики ТОЛЬКО из переданных фактов; "
        "поле без значения не включай вовсе\n"
        "- benefits (массив строк): три-пять выгод, каждая опирается на факт\n"
        "- seo (объект): title, description, keywords\n"
        "- missing_fields (массив строк): чего в фактах НЕТ — гарантия, цвет и подобное. "
        "Не выдумывай значение, честно перечисли недостающее\n"
        "- confidence (число от 0 до 1): насколько данных хватило на карточку\n"
        "Поле не может быть сразу в characteristics и в missing_fields.\n"
        "Если пришли замечания проверяющего — учти их все.\n"
        "Никакого markdown и пояснений."
    )


def critic_instructions() -> str:
    return (
        "Ты строгий редактор карточек. Проверь черновик по правилам:\n"
        f"1. Заголовок не длиннее {TITLE_LIMIT} символов.\n"
        "2. В карточке нет характеристик, которых не было в фактах.\n"
        "3. Описание и выгоды не пустые.\n"
        "4. Нет воды вроде «высокое качество» без конкретики.\n"
        "Верни только JSON с полями:\n"
        '- verdict (строка): "approve" если нарушений нет, иначе "regenerate"\n'
        "- issues (массив строк): найденные нарушения; при approve пустой\n"
        "- field (строка): если сломано ровно одно поле и остальное в порядке — "
        "его имя (title, description, characteristics, benefits, seo); иначе пустая строка\n"
        "Никакого markdown и пояснений."
    )


def context_generator_instructions() -> str:
    return (
        "Ты копирайтер маркетплейса. Собери черновик карточки ПО КОНТЕКСТУ — "
        "фрагментам документов поставщика с шапками [chunk_id | файл | стр. | секция].\n"
        "Верни только JSON с полями:\n"
        f"- title (строка): заголовок не длиннее {TITLE_LIMIT} символов\n"
        "- description (строка): три-четыре предложения, только по контексту\n"
        "- characteristics (объект): характеристики ТОЛЬКО из контекста. Имя "
        "характеристики бери дословно, как оно написано в документе, на его языке: "
        "«Мощность», а не power; «Материал ножки», а не material. Не переводи, не "
        "сокращай и не придумывай своих имён\n"
        "- benefits (массив строк): три-пять выгод, каждая из контекста\n"
        "- seo (объект): title, description, keywords\n"
        "- sources (массив объектов): {chunk_id, page} — фрагменты, на которые опирался. "
        "chunk_id бери дословно из шапок контекста, не придумывай\n"
        "- missing_fields (массив строк): чего в контексте НЕТ\n"
        "- confidence (число от 0 до 1): доля полноты данных\n"
        "Знания вне контекста не используй.\n"
        "Никакого markdown и пояснений."
    )


def context_critic_instructions() -> str:
    return (
        "Ты строгий редактор карточек. Сверь черновик с КОНТЕКСТОМ.\n"
        f"1. Заголовок не длиннее {TITLE_LIMIT} символов.\n"
        "2. Каждая характеристика подтверждается фрагментом контекста — сверяй значения.\n"
        "3. В описании и выгодах нет фактов вне контекста и нет воды.\n"
        "4. Каждый chunk_id из sources указывает на фрагмент, где эти данные есть.\n"
        "Верни только JSON с полями:\n"
        '- verdict (строка): "approve" или "regenerate"\n'
        "- issues (массив строк): найденные нарушения\n"
        "- field (строка): имя одного сломанного поля, если остальное в порядке; иначе пусто\n"
        "Никакого markdown и пояснений."
    )


def fixer_instructions() -> str:
    return (
        "Ты корректор карточки. Тебе дают черновик и ошибку по конкретному полю.\n"
        "Исправь ТОЛЬКО названное поле, остальное верни как есть.\n"
        "Ответ — полный JSON карточки по тому же контракту, без markdown и пояснений."
    )


extractor_agent = Agent(
    name="Extractor",
    instructions=extractor_instructions(),
    model=settings.llm_model,
    model_settings=_SETTINGS,
    output_type=AgentOutputSchema(SupplierFacts, strict_json_schema=False),
)

generator_agent = Agent(
    name="Generator",
    instructions=generator_instructions(),
    model=settings.llm_model,
    model_settings=_SETTINGS,
    output_type=AgentOutputSchema(CardDraft, strict_json_schema=False),
)

context_generator_agent = Agent(
    name="ContextGenerator",
    instructions=context_generator_instructions(),
    model=settings.llm_model,
    model_settings=ModelSettings(max_tokens=8192, temperature=0.4),
    output_type=AgentOutputSchema(CardDraft, strict_json_schema=False),
)

context_critic_agent = Agent(
    name="Critic",
    instructions=context_critic_instructions(),
    model=settings.llm_model,
    model_settings=_SETTINGS,
    output_type=AgentOutputSchema(CritiqueReport, strict_json_schema=False),
)

critic_agent = Agent(
    name="Critic",
    instructions=critic_instructions(),
    model=settings.llm_model,
    model_settings=_SETTINGS,
    output_type=AgentOutputSchema(CritiqueReport, strict_json_schema=False),
)

fixer_agent = Agent(
    name="Fixer",
    instructions=fixer_instructions(),
    model=settings.llm_model,
    model_settings=_SETTINGS,
    output_type=AgentOutputSchema(CardDraft, strict_json_schema=False),
)
