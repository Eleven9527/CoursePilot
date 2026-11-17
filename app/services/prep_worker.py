"""Database-backed handout generation worker."""

import logging
from threading import Event

from fastapi import HTTPException

from app.api.v1.endpoints.prep import LessonScope, authorize_role, build_handout, persist_draft
from app.core.config import settings
from app.core.database import begin_write, connect

logger = logging.getLogger(__name__)


def recover_jobs() -> None:
    with connect() as connection:
        connection.execute("UPDATE prep_jobs SET status='queued',stage='queued' WHERE status='running'")


def process_job() -> bool:
    with connect() as connection:
        begin_write(connection)
        job = connection.execute(
            "SELECT * FROM prep_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        if job is None:
            return False
        job_id = job["id"]
        connection.execute("UPDATE prep_jobs SET status='running',stage='retrieval' WHERE id=?", (job_id,))

    def progress(stage):
        with connect() as connection:
            connection.execute("UPDATE prep_jobs SET stage=? WHERE id=?", (stage, job_id))

    def save(draft):
        authorize_role("teacher", draft.subject, "save_teaching_draft", job_id)
        persist_draft(draft, job_id, queued=True)
        return {"id": job_id}

    try:
        scope = LessonScope.model_validate(dict(job))
        authorize_role("teacher", scope.subject, "search_course_materials", job_id)
        build_handout(scope, save, progress)
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else "讲义生成发生内部错误"
        logger.exception("Handout job %s failed", job_id)
        with connect() as connection:
            connection.execute("UPDATE prep_jobs SET status='failed',error=? WHERE id=?", (detail, job_id))
    return True


def run_prep_worker(stop: Event) -> None:
    while not stop.is_set():
        try:
            if process_job():
                continue
        except Exception:
            logger.exception("Handout queue unavailable")
        stop.wait(max(0.2, settings.worker_poll_interval_seconds))
