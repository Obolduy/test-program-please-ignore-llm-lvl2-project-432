from app.core import db
from app.core.logging import get_logger, setup_logging
from app.rag.embedder import embed_documents
from app.repositories import chunks as chunks_repo

log = get_logger(__name__)

BATCH = 256


def index_pending(conn, doc_id: str | None = None, batch: int = BATCH) -> int:
    total = 0
    while True:
        pending = chunks_repo.chunks_without_embedding(conn, limit=batch, doc_id=doc_id)
        if not pending:
            break
        ids = [chunk_id for chunk_id, _text in pending]
        vectors = embed_documents([text for _id, text in pending])
        chunks_repo.upsert_embeddings(conn, list(zip(ids, vectors)))
        total += len(ids)
        log.info("reindex_batch", batch=len(ids), total=total, doc_id=doc_id or "все")
    return total


def reindex_all(batch: int = BATCH) -> int:
    with db.connection() as conn:
        return index_pending(conn, batch=batch)


def main() -> None:
    setup_logging()
    try:
        total = reindex_all()
    finally:
        db.close_pool()
    print(f"Досчитано векторов: {total}" if total else "Все фрагменты уже с векторами")


if __name__ == "__main__":
    main()
