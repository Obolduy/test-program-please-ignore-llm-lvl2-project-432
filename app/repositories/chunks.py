import psycopg

from app.core.config import settings
from app.rag.embedder import embed_query

RRF_K = 60

_SELECT = "c.id, c.doc_id, c.text, c.metadata, d.filename"


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _row(row) -> dict:
    chunk_id, doc_id, text, metadata, filename, score = row
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "filename": filename,
        "score": float(score) if score is not None else None,
    }


def upsert_embeddings(conn: psycopg.Connection, items: list[tuple[str, list[float]]]) -> int:
    if not items:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
            [(vector_literal(vector), chunk_id) for chunk_id, vector in items],
        )
    return len(items)


def chunks_without_embedding(
    conn: psycopg.Connection, limit: int = 256, doc_id: str | None = None
) -> list[tuple[str, str]]:
    sql = "SELECT id, text FROM chunks WHERE embedding IS NULL"
    args: list = []
    if doc_id:
        sql += " AND doc_id = %s"
        args.append(doc_id)
    sql += " ORDER BY doc_id, ordinal LIMIT %s"
    args.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def search_vector(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int | None = None,
    doc_ids: list[str] | None = None,
    threshold: float | None = None,
) -> list[dict]:
    top_k = top_k or settings.retrieval_top_k
    threshold = settings.retrieval_threshold if threshold is None else threshold
    vector = vector_literal(embed_query(query))
    sql = f"""
        SELECT {_SELECT}, 1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c JOIN documents d ON d.id = c.doc_id
        WHERE c.embedding IS NOT NULL AND d.status = 'indexed'
    """
    args: list = [vector]
    if doc_ids:
        sql += " AND c.doc_id = ANY(%s)"
        args.append(doc_ids)
    sql += " ORDER BY c.embedding <=> %s::vector LIMIT %s"
    args += [vector, top_k * 3]
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    found = [_row(row) for row in rows]
    return [item for item in found if item["score"] is not None and item["score"] >= threshold][
        :top_k
    ]


def search_fts(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int | None = None,
    doc_ids: list[str] | None = None,
) -> list[dict]:
    top_k = top_k or settings.retrieval_top_k
    sql = f"""
        SELECT {_SELECT}, ts_rank(c.tsv, q.query) AS score
        FROM chunks c JOIN documents d ON d.id = c.doc_id,
             plainto_tsquery('russian', %s) AS q(query)
        WHERE c.tsv @@ q.query AND d.status = 'indexed'
    """
    args: list = [query]
    if doc_ids:
        sql += " AND c.doc_id = ANY(%s)"
        args.append(doc_ids)
    sql += " ORDER BY score DESC LIMIT %s"
    args.append(top_k)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [_row(row) for row in cur.fetchall()]


def search_hybrid(
    conn: psycopg.Connection,
    query: str,
    *,
    top_k: int | None = None,
    doc_ids: list[str] | None = None,
    threshold: float | None = None,
) -> list[dict]:
    top_k = top_k or settings.retrieval_top_k
    vector = vector_literal(embed_query(query))
    depth = top_k * 3
    doc_filter = " AND c.doc_id = ANY(%s)" if doc_ids else ""

    sql = f"""
        WITH by_vector AS (
            SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.embedding <=> %s::vector) AS rank
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE c.embedding IS NOT NULL AND d.status = 'indexed'{doc_filter}
            LIMIT %s
        ),
        by_words AS (
            SELECT c.id, ROW_NUMBER() OVER (ORDER BY ts_rank(c.tsv, q.query) DESC) AS rank
            FROM chunks c JOIN documents d ON d.id = c.doc_id,
                 plainto_tsquery('russian', %s) AS q(query)
            WHERE c.tsv @@ q.query AND d.status = 'indexed'{doc_filter}
            LIMIT %s
        )
        SELECT {_SELECT},
               COALESCE(1.0 / (%s + v.rank), 0) + COALESCE(1.0 / (%s + w.rank), 0) AS score,
               1 - (c.embedding <=> %s::vector) AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.doc_id
        LEFT JOIN by_vector v ON v.id = c.id
        LEFT JOIN by_words w ON w.id = c.id
        WHERE v.id IS NOT NULL OR w.id IS NOT NULL
        ORDER BY score DESC
        LIMIT %s
    """
    args: list = [vector]
    if doc_ids:
        args.append(doc_ids)
    args.append(depth)
    args.append(query)
    if doc_ids:
        args.append(doc_ids)
    args += [depth, RRF_K, RRF_K, vector, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return [
        {**_row(row[:5] + (row[6],)), "rrf_score": float(row[5])}
        for row in rows
    ]


def get_chunks_by_ids(conn: psycopg.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.doc_id, c.text, c.metadata, d.filename "
            "FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id = ANY(%s)",
            (ids,),
        )
        rows = cur.fetchall()
    return {row[0]: _row(row + (None,)) for row in rows}
