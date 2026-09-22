import hashlib
import json
import uuid

import psycopg


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def create_document(
    conn: psycopg.Connection, filename: str, content: bytes, kind: str
) -> tuple[str, bool]:
    digest = content_hash(content)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (id, filename, content_hash, kind) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (content_hash) DO NOTHING RETURNING id",
            (uuid.uuid4().hex[:12], filename, digest, kind),
        )
        row = cur.fetchone()
        if row:
            return row[0], True
        cur.execute("SELECT id FROM documents WHERE content_hash = %s", (digest,))
        return cur.fetchone()[0], False


def set_status(
    conn: psycopg.Connection, doc_id: str, status: str, *, error: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET status = %s, error = %s, updated_at = now() WHERE id = %s",
            (status, error, doc_id),
        )


def set_chunks_count(conn: psycopg.Connection, doc_id: str, count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET chunks_count = %s, updated_at = now() WHERE id = %s",
            (count, doc_id),
        )


def delete_chunks(conn: psycopg.Connection, doc_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))


def insert_chunks(conn: psycopg.Connection, chunks: list[dict]) -> None:
    if not chunks:
        return
    rows = [
        (
            chunk["id"],
            chunk["metadata"]["doc_id"],
            chunk["ordinal"],
            chunk["text"],
            json.dumps(chunk["metadata"], ensure_ascii=False),
        )
        for chunk in chunks
    ]
    with conn.cursor() as cur, conn.transaction():
        cur.executemany(
            "INSERT INTO chunks (id, doc_id, ordinal, text, metadata) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )


_FIELDS = "id, filename, kind, status, chunks_count, error, created_at"


def _as_dict(row) -> dict:
    doc_id, filename, kind, status, count, error, created = row
    return {
        "id": doc_id,
        "filename": filename,
        "kind": kind,
        "status": status,
        "chunks_count": count,
        "error": error,
        "created_at": str(created),
    }


def get_document(conn: psycopg.Connection, doc_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_FIELDS} FROM documents WHERE id = %s", (doc_id,))
        row = cur.fetchone()
    return _as_dict(row) if row else None


def list_documents(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_FIELDS} FROM documents ORDER BY created_at")
        return [_as_dict(row) for row in cur.fetchall()]
