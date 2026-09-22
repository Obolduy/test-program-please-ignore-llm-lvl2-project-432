from fastapi import APIRouter, HTTPException

from app.temporal.client import temporal_client

router = APIRouter(tags=["workflows"], prefix="/workflows")


@router.get("/{wf_id}")
async def workflow_status(wf_id: str):
    client = await temporal_client()
    handle = client.get_workflow_handle(wf_id)
    try:
        description = await handle.describe()
        status = await handle.query("current_status")
    except Exception as exc:
        raise HTTPException(404, f"процесс не найден: {exc}") from exc
    return {"id": wf_id, "run_status": str(description.status), "status": status}


@router.post("/{wf_id}/approve")
async def approve(wf_id: str):
    return await _signal(wf_id, "approve")


@router.post("/{wf_id}/request-changes")
async def request_changes(wf_id: str):
    return await _signal(wf_id, "request_changes")


@router.get("/{wf_id}/result")
async def workflow_result(wf_id: str):
    client = await temporal_client()
    handle = client.get_workflow_handle(wf_id)
    try:
        return {"id": wf_id, "result": await handle.result()}
    except Exception as exc:
        raise HTTPException(409, f"процесс ещё не завершён: {exc}") from exc


async def _signal(wf_id: str, name: str):
    client = await temporal_client()
    handle = client.get_workflow_handle(wf_id)
    try:
        await handle.signal(name)
    except Exception as exc:
        raise HTTPException(404, f"процесс не найден: {exc}") from exc
    return {"id": wf_id, "signaled": name}
