from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request

from app.core import db
from app.core.logging import setup_logging
from app.routers import cards, documents, generate, health, jobs, workflows


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    db.pool()
    yield
    db.close_pool()


app = FastAPI(title="product-card-ai", lifespan=lifespan)


@app.middleware("http")
async def bind_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex[:12]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(health.router)
app.include_router(cards.router)
app.include_router(jobs.router)
app.include_router(workflows.router)
app.include_router(documents.router)
app.include_router(generate.router)
