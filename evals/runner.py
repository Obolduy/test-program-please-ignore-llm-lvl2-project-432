import argparse
import asyncio
import json
import time
from pathlib import Path

from app.core import db
from app.core.logging import get_logger, setup_logging
from app.repositories import chunks as chunks_repo
from app.repositories import documents as docs_repo
from app.repositories import llm_calls as calls_repo
from app.services import rag_pipeline
from evals.judge import judge_faithfulness
from evals.metrics import citation_hit, field_accuracy

log = get_logger(__name__)

DATA = Path(__file__).resolve().parents[1] / "data"
REPORT = Path(__file__).resolve().parent / "report.json"


def load_golden() -> dict:
    return json.loads((DATA / "golden_cards.json").read_text(encoding="utf-8"))


async def evaluate(doc_id: str, golden: dict, job_id: str) -> dict:
    query = golden.get("product") or "характеристики товара"
    started = time.monotonic()
    context, guard = await rag_pipeline.retrieve_context_async(query, [doc_id])
    draft, attempts, _verdict, status, _guard = await rag_pipeline.run_rag_pipeline(
        query, [doc_id], context=context
    )
    elapsed = time.monotonic() - started
    card = draft.model_dump()

    with db.connection() as conn:
        claimed = [source["chunk_id"] for source in card["sources"]]
        chunks = chunks_repo.get_chunks_by_ids(conn, claimed) if claimed else {}

    try:
        faithfulness = (await judge_faithfulness(context, draft.model_dump_json())).faithfulness
    except Exception as exc:
        log.warning("judge_unavailable", error=repr(exc))
        faithfulness = None

    with db.connection() as conn:
        spend = calls_repo.job_cost(conn, job_id)

    return {
        "status": status,
        "attempts": attempts,
        "seconds": round(elapsed, 1),
        "field_accuracy": round(field_accuracy(card["characteristics"], golden.get("characteristics", {})), 3),
        "citation_hit": round(citation_hit(card["sources"], golden.get("source_probes", {}), chunks), 3),
        "faithfulness": None if faithfulness is None else round(faithfulness, 3),
        "confidence": card["confidence"],
        "missing_fields": card["missing_fields"],
        "characteristics": card["characteristics"],
        "title": card["title"],
        "cost": spend["cost"],
        "llm_calls": spend["calls"],
        "guard": guard.as_dict(),
    }


def _print_table(results: dict) -> None:
    header = f"{'документ':26}{'характ.':>9}{'цитир.':>8}{'судья':>8}{'увер.':>7}{'состояние':>13}{'сек':>6}"
    print(header)
    print("-" * len(header))
    for name, row in results.items():
        judge = "—" if row["faithfulness"] is None else f"{row['faithfulness']:.2f}"
        print(
            f"{name:26}{row['field_accuracy']:>9.2f}{row['citation_hit']:>8.2f}"
            f"{judge:>8}{row['confidence']:>7.2f}{row['status']:>13}{row['seconds']:>6.0f}"
        )
    if not results:
        return
    print("-" * len(header))
    count = len(results)
    judged = [r["faithfulness"] for r in results.values() if r["faithfulness"] is not None]
    average_judge = f"{sum(judged) / len(judged):.2f}" if judged else "—"
    print(
        f"{'СРЕДНЕЕ':26}"
        f"{sum(r['field_accuracy'] for r in results.values()) / count:>9.2f}"
        f"{sum(r['citation_hit'] for r in results.values()) / count:>8.2f}"
        f"{average_judge:>8}"
    )


async def run_all(selected: dict, known: dict) -> dict:
    import structlog

    run_tag = time.strftime("%Y%m%d-%H%M%S")
    results: dict[str, dict] = {}
    for name, expected in selected.items():
        document = known.get(name)
        if not document or document["status"] != "indexed":
            print(f"{name:26} пропуск: документ не проиндексирован")
            continue
        job_id = f"eval-{run_tag}-{document['id']}"
        structlog.contextvars.bind_contextvars(job_id=job_id)
        try:
            results[name] = await evaluate(document["id"], expected, job_id)
        finally:
            structlog.contextvars.unbind_contextvars("job_id")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="прогон метрик генерации")
    parser.add_argument("--full", action="store_true", help="весь набор, а не подмножество")
    args = parser.parse_args()

    setup_logging()
    golden = load_golden()
    selected = golden["documents"]
    if not args.full:
        defaults = set(golden.get("eval_defaults", []))
        selected = {name: item for name, item in selected.items() if name in defaults}

    with db.connection() as conn:
        known = {doc["filename"]: doc for doc in docs_repo.list_documents(conn)}

    results = asyncio.run(run_all(selected, known))

    print()
    _print_table(results)
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт сохранён: {REPORT}")


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close_pool()
