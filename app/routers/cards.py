from fastapi import APIRouter, HTTPException

from app.schemas.cards import CardDraft
from app.schemas.jobs import CardRequest
from app.services.pipeline import run_pipeline

router = APIRouter(tags=["cards"])


@router.post("/cards", response_model=CardDraft)
async def create_card(body: CardRequest) -> CardDraft:
    draft, _attempts, _verdict, _status = await run_pipeline(body.supplier_text)
    if draft is None:
        raise HTTPException(502, "модель не вернула карточку")
    return draft
