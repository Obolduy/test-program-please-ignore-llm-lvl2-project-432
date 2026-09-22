from app.core.logging import get_logger
from app.parsers.chunker import chunk_blocks
from app.parsers.docx import parse_docx
from app.parsers.normalizer import normalize
from app.parsers.pdf import PdfNoTextLayer, parse_pdf
from app.parsers.xlsx import parse_xlsx
from app.repositories import documents as docs_repo

log = get_logger(__name__)

ALLOWED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024

_PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx}


def parse_to_chunks(content: bytes, kind: str, doc_id: str) -> list[dict]:
    parser = _PARSERS.get(kind)
    if parser is None:
        raise ValueError(f"неподдерживаемый формат: {kind}")
    return chunk_blocks(normalize(parser(content)), doc_id)


def ingest(conn, doc_id: str, content: bytes, kind: str, *, embed: bool = True) -> int:
    docs_repo.set_status(conn, doc_id, "parsing")
    try:
        chunks = parse_to_chunks(content, kind, doc_id)
    except PdfNoTextLayer as exc:
        docs_repo.set_status(conn, doc_id, "failed", error=str(exc))
        log.warning("document_failed", doc_id=doc_id, reason="no text layer")
        return 0
    except Exception as exc:
        docs_repo.set_status(conn, doc_id, "failed", error=f"разбор не удался: {exc!r}")
        log.error("document_failed", doc_id=doc_id, error=repr(exc))
        raise

    docs_repo.delete_chunks(conn, doc_id)
    docs_repo.insert_chunks(conn, chunks)
    docs_repo.set_chunks_count(conn, doc_id, len(chunks))
    docs_repo.set_status(conn, doc_id, "indexed")
    log.info("document_indexed", doc_id=doc_id, kind=kind, chunks=len(chunks))

    if embed and chunks:
        from app.rag.reindex import index_pending

        try:
            vectors = index_pending(conn, doc_id)
            log.info("document_embedded", doc_id=doc_id, vectors=vectors)
        except Exception as exc:
            docs_repo.set_status(conn, doc_id, "embed_failed", error=f"эмбеддинги: {exc!r}")
            log.error("document_embed_failed", doc_id=doc_id, error=repr(exc))
    return len(chunks)
