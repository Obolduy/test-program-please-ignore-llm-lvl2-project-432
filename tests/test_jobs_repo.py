import os

import pytest

from app.core import db
from app.repositories import jobs as jobs_repo
from app.schemas.cards import CardDraft

pytestmark = pytest.mark.skipif(
    os.environ.get("PCA_SKIP_DB_TESTS") == "1", reason="PCA_SKIP_DB_TESTS=1"
)


@pytest.fixture
def conn():
    with db.connection() as connection:
        created: list[str] = []
        yield connection, created
        with connection.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = ANY(%s)", (created,))


def test_create_job_returns_new_id(conn):
    connection, created = conn
    job_id, was_created = jobs_repo.create_job(connection, {"supplier_text": "блендер"})
    created.append(job_id)
    assert was_created
    job = jobs_repo.get_job(connection, job_id)
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert "result" not in job


def test_same_idempotency_key_returns_same_job(conn):
    connection, created = conn
    key = "ключ-" + jobs_repo.new_id()
    first, first_created = jobs_repo.create_job(connection, {"supplier_text": "а"}, key)
    second, second_created = jobs_repo.create_job(connection, {"supplier_text": "а"}, key)
    created.append(first)
    assert first == second
    assert first_created and not second_created


def test_missing_idempotency_key_creates_separate_jobs(conn):
    connection, created = conn
    first, _ = jobs_repo.create_job(connection, {"supplier_text": "а"})
    second, _ = jobs_repo.create_job(connection, {"supplier_text": "а"})
    created += [first, second]
    assert first != second


def test_set_status_writes_result_and_counts_attempts(conn):
    connection, created = conn
    job_id, _ = jobs_repo.create_job(connection, {"supplier_text": "блендер"})
    created.append(job_id)
    draft = CardDraft(title="Блендер", description="Описание", benefits=["ножка"])

    jobs_repo.set_status(connection, job_id, "generating", bump_attempts=True)
    jobs_repo.set_status(
        connection, job_id, "approved", result=draft,
        guard={"masked_pii": 2, "suspicious_chunks": ["c7"]},
    )

    job = jobs_repo.get_job(connection, job_id)
    assert job["status"] == "approved"
    assert job["attempts"] == 1
    assert job["result"]["title"] == "Блендер"
    assert job["guard"] == {"masked_pii": 2, "suspicious_chunks": ["c7"]}


def test_get_job_returns_none_for_unknown_id(conn):
    connection, _created = conn
    assert jobs_repo.get_job(connection, "нет-такой") is None
