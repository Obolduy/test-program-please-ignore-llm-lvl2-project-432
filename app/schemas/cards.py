from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TITLE_LIMIT = 60


class SupplierFacts(BaseModel):

    product_name: str = Field(description="Название товара, как оно в тексте")
    characteristics: dict[str, str] = Field(
        default_factory=dict, description="Характеристики парами ключ-значение"
    )
    missing_fields: list[str] = Field(
        default_factory=list, description="Чего в тексте нет: гарантия, цвет и подобное"
    )


class SourceRef(BaseModel):

    chunk_id: str = Field(description="Идентификатор фрагмента в базе")
    doc_id: str = Field(default="", description="Идентификатор документа")
    page: int | None = Field(default=None, description="Страница источника")
    score: float | None = Field(default=None, description="Релевантность фрагмента")


class Seo(BaseModel):

    title: str = Field(default="", description="Заголовок для поисковой выдачи")
    description: str = Field(default="", description="Описание для поисковой выдачи")
    keywords: list[str] = Field(default_factory=list)


class CardDraft(BaseModel):

    title: str = Field(max_length=TITLE_LIMIT, description=f"Заголовок до {TITLE_LIMIT} символов")
    description: str = Field(description="Описание на три-четыре предложения")
    characteristics: dict[str, str] = Field(default_factory=dict)
    benefits: list[str] = Field(default_factory=list, description="Три-пять выгод")
    seo: Seo = Field(default_factory=Seo)
    sources: list[SourceRef] = Field(
        default_factory=list, description="Фрагменты, на которые опираются утверждения"
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Чего в документах не нашлось. Поле сюда, а не выдуманное значение",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Самооценка: 0 — данных нет, 1 — всё подтверждено источниками",
    )

    @field_validator("characteristics")
    @classmethod
    def drop_empty_values(cls, value: dict[str, str]) -> dict[str, str]:
        return {key: val for key, val in value.items() if str(val).strip()}

    @model_validator(mode="after")
    def field_cannot_be_known_and_missing(self) -> "CardDraft":
        both = sorted(set(self.missing_fields) & set(self.characteristics))
        if both:
            raise ValueError(
                f"поля указаны одновременно в characteristics и в missing_fields: {both}"
            )
        return self


class CritiqueReport(BaseModel):

    verdict: Literal["approve", "regenerate"] = Field(
        description="approve — карточка годится, regenerate — переделать"
    )
    issues: list[str] = Field(
        default_factory=list, description="Найденные нарушения; при approve пусто"
    )
    field: str = Field(
        default="",
        description="Имя одного сломанного поля, если всё остальное в порядке. "
        "Нарушений несколько или поле не одно — оставь пустым",
    )
