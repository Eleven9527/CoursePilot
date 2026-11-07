from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.enums import ParseStepKey
from app.services.document_service import initialize_database, recover_interrupted_steps
from app.services.worker_service import run_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    recover_interrupted_steps()
    stop_event = Event()
    workers = [
        Thread(
            target=run_worker,
            args=(stop_event, step_key),
            name=f"document-worker-{step_key.value}",
            daemon=True,
        )
        for step_key in (ParseStepKey.MINERU_PARSE, ParseStepKey.CHUNKING)
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
