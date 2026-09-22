from fastapi import APIRouter, HTTPException

from app.core import db

READY_TIMEOUT_S = 3.0

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, object]:
    try:
        with db.connection(timeout=READY_TIMEOUT_S) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            has_vector = cur.fetchone() is not None
    except Exception as exc:
        raise HTTPException(503, f"база недоступна: {exc}") from exc
    if not has_vector:
        raise HTTPException(503, "расширение vector не включено: примените миграции")
    return {"status": "ok", "vector": True}
