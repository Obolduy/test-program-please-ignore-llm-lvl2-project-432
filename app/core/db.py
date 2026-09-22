import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import settings

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = ConnectionPool(
                    settings.database_url,
                    min_size=settings.db_pool_min,
                    max_size=settings.db_pool_max,
                    kwargs={"autocommit": True},
                    open=True,
                )
    return _pool


@contextmanager
def connection(timeout: float | None = None) -> Iterator[psycopg.Connection]:
    kwargs = {} if timeout is None else {"timeout": timeout}
    with pool().connection(**kwargs) as conn:
        yield conn


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
