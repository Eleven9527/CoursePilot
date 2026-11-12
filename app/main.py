from contextlib import asynccontextmanager
import logging
from html import escape
from pathlib import Path
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.enums import ParseStepKey
from app.rag.vector_store.milvus import list_collections
from app.services.document_service import (
    initialize_database, migrate_chunk_files, queue_existing_embeddings, recover_interrupted_steps,
)
from app.services.worker_service import run_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    embedding_ready = settings.embedding_enabled
    if settings.milvus_uri:
        try:
            list_collections()
        except RuntimeError as exc:
            embedding_ready = False
            logging.getLogger(__name__).warning("Milvus 连接失败，本次启动暂停向量化 Worker：%s", exc)
    initialize_database()
    migrate_chunk_files()
    recover_interrupted_steps()
    step_keys = [ParseStepKey.MINERU_PARSE, ParseStepKey.CHUNKING]
    if embedding_ready:
        queue_existing_embeddings()
        step_keys.append(ParseStepKey.EMBEDDING)
    stop_event = Event()
    workers = [
        Thread(
            target=run_worker,
            args=(stop_event, step_key),
            name=f"document-worker-{step_key.value}",
            daemon=True,
        )
        for step_key in step_keys
    ]
    for worker in workers:
        worker.start()
    try:
        yield
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=5)


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["root"])
def read_root() -> dict[str, str]:
    return {"message": "RAG API is running", "docs": "/docs"}


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "admin.html")


@app.get("/assets/vue.global.prod.js", include_in_schema=False)
def vue_runtime() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "vendor" / "vue.global.prod.js",
                        media_type="text/javascript")


@app.get("/qa", include_in_schema=False)
def qa_page() -> HTMLResponse:
    page = (Path(__file__).parent / "static" / "qa.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("__QA_API_PREFIX__", escape(settings.api_prefix, quote=True)))
