import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.core import db
from app.core.config import settings
from app.repositories import documents as docs_repo
from app.services.documents import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from app.temporal.client import temporal_client
from app.temporal.workflows import ParseDocumentWorkflow

router = APIRouter(tags=["documents"], prefix="/documents")

UPLOAD_DIR = Path(tempfile.gettempdir()) / "product-card-ai"


@router.post("", status_code=202)
async def upload_document(file: UploadFile):
    kind = _kind_or_415(file.filename or "")
    content = await file.read()
    if not content:
        raise HTTPException(400, "пустой файл")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"файл больше {MAX_FILE_SIZE // 1024 // 1024} МБ")

    with db.connection() as conn:
        doc_id, created = docs_repo.create_document(conn, file.filename, content, kind)

    if not created:
        return {"id": doc_id, "status": "already known"}

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / doc_id
    path.write_bytes(content)

    client = await temporal_client()
    await client.start_workflow(
        ParseDocumentWorkflow.run,
        args=[doc_id, str(path), kind],
        id=f"parse-{doc_id}",
        task_queue=settings.temporal_task_queue,
    )
    return {"id": doc_id, "status": "new"}


@router.get("")
async def list_documents():
    with db.connection() as conn:
        return docs_repo.list_documents(conn)


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    with db.connection() as conn:
        document = docs_repo.get_document(conn, doc_id)
    if not document:
        raise HTTPException(404, "документ не найден")
    return document


def _kind_or_415(filename: str) -> str:
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = ALLOWED_EXTENSIONS.get(extension)
    if kind is None:
        raise HTTPException(415, f"поддерживаются: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    return kind
