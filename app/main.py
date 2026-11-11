from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.services.document_service import initialize_database, recover_interrupted_processing
from app.services.worker_service import run_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    recover_interrupted_processing()
    stop_event = Event()
    worker_thread = Thread(
        target=run_worker,
        args=(stop_event,),
        name="document-worker",
        daemon=True,
    )
    worker_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        worker_thread.join(timeout=5)


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["root"])
def read_root() -> dict[str, str]:
    return {"message": "RAG API is running", "docs": "/docs"}


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "admin.html")
