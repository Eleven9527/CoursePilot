from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: str
    title: str
    grade: str
    unit: str
    description: str
    filename: str
    file_type: str
    size_bytes: int
    parsing_status: str
    parse_error: str | None = None
    current_task_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ParseTaskResponse(BaseModel):
    id: str
    document_id: str
    status: str
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ParseStepResponse(BaseModel):
    id: str
    task_id: str
    document_id: str
    step_key: str
    title: str
    status: str
    error: str | None = None
    artifact_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
