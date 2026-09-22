from app.core import db
from app.core.config import settings
from app.repositories import chunks as chunks_repo

MODES = {
    "vector": chunks_repo.search_vector,
    "fts": chunks_repo.search_fts,
    "hybrid": chunks_repo.search_hybrid,
}


def search(
    query: str,
    *,
    mode: str = "hybrid",
    doc_ids: list[str] | None = None,
    brand: str | None = None,
    articul: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    searcher = MODES.get(mode)
    if searcher is None:
        raise ValueError(f"неизвестный режим поиска: {mode}; есть {', '.join(MODES)}")
    with db.connection() as conn:
        found = searcher(conn, query, top_k=top_k or settings.retrieval_top_k, doc_ids=doc_ids)
    if brand:
        found = [item for item in found if item["metadata"].get("brand") == brand]
    if articul:
        found = [item for item in found if item["metadata"].get("articul") == articul]
    return found
