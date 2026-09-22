from pathlib import Path

import psycopg

from app.core import db

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def applied(conn: psycopg.Connection) -> set[str]:
    conn.execute(_LEDGER)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {version for (version,) in cur.fetchall()}


def run_migrations() -> list[str]:
    with db.connection() as conn:
        done = applied(conn)
        fresh: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            fresh.append(version)
        return fresh


def main() -> None:
    try:
        fresh = run_migrations()
    finally:
        db.close_pool()
    print("Применено: " + ", ".join(fresh) if fresh else "Новых миграций нет")


if __name__ == "__main__":
    main()
