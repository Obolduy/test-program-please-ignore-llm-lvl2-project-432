import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.schemas.cards import CritiqueReport
    from app.temporal.activities import (
        critique_activity,
        extract_activity,
        generate_activity,
        parse_document_activity,
        rag_card_activity,
        set_job_status_activity,
    )

STAGE_TIMEOUT = timedelta(seconds=300)
STATUS_TIMEOUT = timedelta(seconds=30)
PARSE_TIMEOUT = timedelta(minutes=10)
RAG_TIMEOUT = timedelta(minutes=15)

RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class ParseDocumentWorkflow:

    @workflow.run
    async def run(self, doc_id: str, path: str, kind: str) -> int:
        return await workflow.execute_activity(
            parse_document_activity,
            args=[doc_id, path, kind],
            start_to_close_timeout=PARSE_TIMEOUT,
            retry_policy=RETRY,
        )


@workflow.defn
class RagCardWorkflow:

    def __init__(self) -> None:
        self._status = "starting"
        self._decision: str | None = None

    @workflow.run
    async def run(self, job_id: str, document_ids: list[str], product_hint: str = "") -> str:
        outcome = await workflow.execute_activity(
            rag_card_activity,
            args=[job_id, document_ids, product_hint],
            start_to_close_timeout=RAG_TIMEOUT,
            retry_policy=RETRY,
        )
        card_json = json.dumps(json.loads(outcome)["card"], ensure_ascii=False)
        guard_json = json.dumps(json.loads(outcome)["guard"], ensure_ascii=False)

        await self._publish(job_id, "awaiting_human", card_json, guard_json)
        await workflow.wait_condition(lambda: self._decision is not None)

        final = "approved" if self._decision == "approve" else "rejected"
        await self._publish(job_id, final, card_json, guard_json)
        return card_json

    async def _publish(
        self, job_id: str, status: str, card_json: str, guard_json: str
    ) -> None:
        self._status = status
        await workflow.execute_activity(
            set_job_status_activity,
            args=[job_id, status, card_json, None, guard_json],
            start_to_close_timeout=STATUS_TIMEOUT,
            retry_policy=RETRY,
        )

    @workflow.signal
    def approve(self) -> None:
        self._decision = "approve"

    @workflow.signal
    def request_changes(self) -> None:
        self._decision = "request_changes"

    @workflow.query
    def current_status(self) -> str:
        return self._status


def _feedback_arg(feedback: list[str]) -> str | None:
    return json.dumps(feedback, ensure_ascii=False) if feedback else None


@workflow.defn
class CardWorkflow:

    def __init__(self) -> None:
        self._status = "starting"
        self._decision: str | None = None

    @workflow.run
    async def run(self, job_id: str, supplier_text: str, max_attempts: int = 3) -> str:
        await self._publish(job_id, "extracting")
        facts_json = await workflow.execute_activity(
            extract_activity,
            supplier_text,
            start_to_close_timeout=STAGE_TIMEOUT,
            retry_policy=RETRY,
        )

        feedback: list[str] = []
        draft_json = "{}"
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            await self._publish(job_id, "generating")
            draft_json = await workflow.execute_activity(
                generate_activity,
                args=[facts_json, _feedback_arg(feedback)],
                start_to_close_timeout=STAGE_TIMEOUT,
                retry_policy=RETRY,
            )
            await self._publish(job_id, "critiquing")
            report = CritiqueReport.model_validate_json(
                await workflow.execute_activity(
                    critique_activity,
                    args=[facts_json, draft_json],
                    start_to_close_timeout=STAGE_TIMEOUT,
                    retry_policy=RETRY,
                )
            )
            if report.verdict == "approve":
                break
            feedback = report.issues

        await self._publish(job_id, "awaiting_human", draft_json)
        await workflow.wait_condition(lambda: self._decision is not None)

        await self._publish(
            job_id, "approved" if self._decision == "approve" else "rejected", draft_json
        )
        return draft_json

    async def _publish(self, job_id: str, status: str, draft_json: str | None = None) -> None:
        self._status = status
        await workflow.execute_activity(
            set_job_status_activity,
            args=[job_id, status, draft_json, None],
            start_to_close_timeout=STATUS_TIMEOUT,
            retry_policy=RETRY,
        )

    @workflow.signal
    def approve(self) -> None:
        self._decision = "approve"

    @workflow.signal
    def request_changes(self) -> None:
        self._decision = "request_changes"

    @workflow.query
    def current_status(self) -> str:
        return self._status
