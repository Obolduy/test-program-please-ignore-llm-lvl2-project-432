from decimal import Decimal

import psycopg


def insert_call(
    conn: psycopg.Connection,
    *,
    job_id: str | None,
    agent: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost: Decimal,
    latency_ms: int | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO llm_calls "
            "(job_id, agent, model, prompt_tokens, completion_tokens, cost, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (job_id, agent, model, prompt_tokens, completion_tokens, cost, latency_ms),
        )


def job_cost(conn: psycopg.Connection, job_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), coalesce(sum(cost), 0), coalesce(sum(prompt_tokens), 0), "
            "coalesce(sum(completion_tokens), 0), coalesce(sum(latency_ms), 0) "
            "FROM llm_calls WHERE job_id = %s",
            (job_id,),
        )
        calls, cost, prompt_tokens, completion_tokens, latency = cur.fetchone()
    return {
        "job_id": job_id,
        "calls": int(calls),
        "cost": str(cost),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "latency_ms": int(latency),
    }


def by_model(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model, count(*), coalesce(sum(cost), 0) FROM llm_calls "
            "GROUP BY model ORDER BY 3 DESC, 2 DESC"
        )
        rows = cur.fetchall()
    return [{"model": m, "calls": int(n), "cost": str(c)} for m, n, c in rows]
