import json
import uuid

import psycopg

from app.schemas.cards import CardDraft


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create_job(
    conn: psycopg.Connection, payload: dict, idempotency_key: str | None = None
) -> tuple[str, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (id, idempotency_key, payload) VALUES (%s, %s, %s) "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
            (new_id(), idempotency_key, json.dumps(payload, ensure_ascii=False)),
        )
        row = cur.fetchone()
        if row:
            return row[0], True
        cur.execute("SELECT id FROM jobs WHERE idempotency_key = %s", (idempotency_key,))
        return cur.fetchone()[0], False


def set_status(
    conn: psycopg.Connection,
    job_id: str,
    status: str,
    *,
    result: CardDraft | None = None,
    guard: dict | None = None,
    error: str | None = None,
    bump_attempts: bool = False,
) -> None:
    assignments = ["status = %s", "updated_at = now()"]
    args: list = [status]
    if result is not None:
        assignments.append("result = %s")
        args.append(result.model_dump_json())
    if guard is not None:
        assignments.append("guard = %s")
        args.append(json.dumps(guard, ensure_ascii=False))
    if error is not None:
        assignments.append("error = %s")
        args.append(error)
    if bump_attempts:
        assignments.append("attempts = attempts + 1")
    args.append(job_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = %s", args)


def get_job(conn: psycopg.Connection, job_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, attempts, result, error, guard FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    job_id, status, attempts, result, error, guard = row
    job = {"id": job_id, "status": status, "attempts": attempts, "error": error}
    if result is not None:
        job["result"] = result if isinstance(result, dict) else json.loads(result)
    if guard is not None:
        job["guard"] = guard if isinstance(guard, dict) else json.loads(guard)
    return job
