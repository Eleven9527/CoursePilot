from contextlib import asynccontextmanager
import logging
from html import escape
from pathlib import Path
from secrets import token_hex
from threading import Event, Thread

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.auth import authenticate, current_role
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
app.add_middleware(SessionMiddleware, secret_key=token_hex(32), max_age=8 * 3600)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["root"])
def read_root() -> dict[str, str]:
    return {"message": "RAG API is running", "docs": "/docs"}


@app.get("/admin", include_in_schema=False)
def admin_page(request: Request):
    role = current_role(request)
    if role != "teacher":
        return RedirectResponse("/qa" if role else "/login", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "admin.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(Path(__file__).parent / "static" / "login.html")


@app.post("/login", include_in_schema=False)
def login(request: Request, account: str = Form(...), password: str = Form(...)):
    if not authenticate(account, password):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session.clear()
    request.session["account"] = account
    return RedirectResponse("/admin" if account == "teacher" else "/qa", status_code=303)


@app.post("/logout", include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/assets/sidebar.css", include_in_schema=False)
def sidebar_styles() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "sidebar.css", media_type="text/css")


@app.get("/assets/vue.global.prod.js", include_in_schema=False)
def vue_runtime() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "vendor" / "vue.global.prod.js",
                        media_type="text/javascript")


@app.get("/qa", include_in_schema=False)
def qa_page(request: Request):
    if current_role(request) is None:
        return RedirectResponse("/login", status_code=303)
    page = (Path(__file__).parent / "static" / "qa.html").read_text(encoding="utf-8")
    if current_role(request) == "student":
        page = page.replace('<a class="nav-link" href="/admin"><span aria-hidden="true">▤</span>文档管理</a>', "")
    return HTMLResponse(page.replace("__QA_API_PREFIX__", escape(settings.api_prefix, quote=True)))
