import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.enums import DocumentStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    """初始化文档表；处理进度只保存在 documents.status。"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                grade TEXT NOT NULL DEFAULT '未指定', unit TEXT NOT NULL DEFAULT '未指定', description TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL, stored_name TEXT NOT NULL, file_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, status TEXT NOT NULL,
                processing_error TEXT, mineru_result_path TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )


def recover_interrupted_processing() -> None:
    """服务重启后把处理中断的状态退回到该阶段的入口，让 Worker 重做这一阶段。"""
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE documents SET status=?,processing_error=NULL WHERE status=?",
            (DocumentStatus.SOURCE_SAVED.value, DocumentStatus.MINERU_PARSING.value),
        )
        connection.execute(
            "UPDATE documents SET status=?,processing_error=NULL WHERE status=?",
            (DocumentStatus.MINERU_PARSED.value, DocumentStatus.CHUNKING.value),
        )


def _document(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in (
        "id", "title", "grade", "unit", "description", "filename", "stored_name", "file_type",
        "size_bytes", "status", "processing_error", "mineru_result_path", "created_at", "updated_at",
    )}


def list_documents() -> list[dict]:
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [_document(row) for row in rows]


def get_document(document_id: str) -> dict | None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    return _document(row) if row else None


def get_stored_path(document_id: str) -> Path | None:
    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute("SELECT stored_name FROM documents WHERE id=?", (document_id,)).fetchone()
    return settings.upload_dir / row[0] if row else None


def get_chunks_path(document_id: str) -> Path:
    return settings.parsed_dir / document_id / "chunks.jsonl"


def create_document(document_id: str, title: str, grade: str, unit: str, description: str,
                    filename: str, stored_name: str, file_type: str, size_bytes: int) -> dict:
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """INSERT INTO documents
            (id,title,grade,unit,description,filename,stored_name,file_type,size_bytes,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (document_id,title,grade,unit,description,filename,stored_name,file_type,size_bytes,
             DocumentStatus.SOURCE_SAVED.value,now,now),
        )
    document = get_document(document_id)
    if document is None:
        raise RuntimeError("新建文档后未能从数据库读取记录")
    return document


def update_document(document_id: str, title: str, grade: str, unit: str, description: str,
                    replacement: tuple[str, str, str, int] | None = None) -> dict | None:
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
        if replacement:
            filename, stored_name, file_type, size_bytes = replacement
            connection.execute(
                """UPDATE documents SET title=?,grade=?,unit=?,description=?,filename=?,stored_name=?,file_type=?,size_bytes=?,
                status=?,processing_error=NULL,mineru_result_path=NULL,updated_at=? WHERE id=?""",
                (title,grade,unit,description,filename,stored_name,file_type,size_bytes,
                 DocumentStatus.SOURCE_SAVED.value,now,document_id),
            )
        else:
            connection.execute(
                "UPDATE documents SET title=?,grade=?,unit=?,description=?,updated_at=? WHERE id=?",
                (title,grade,unit,description,now,document_id),
            )
        if connection.total_changes == 0:
            return None
    return get_document(document_id)


def delete_document(document_id: str) -> tuple[Path, Path] | None:
    document = get_document(document_id)
    if document is None:
        return None
    stored_path = settings.upload_dir / document["stored_name"]
    artifact_dir = settings.parsed_dir / document_id
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
    return stored_path, artifact_dir


def queue_processing(document_id: str, *, force: bool = False) -> bool:
    """把单一文档状态设为流水线入口，Worker 随后按状态推进。"""
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT status FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            connection.rollback()
            return False
        if row[0] in {DocumentStatus.SOURCE_SAVED.value, DocumentStatus.MINERU_PARSING.value,
                      DocumentStatus.MINERU_PARSED.value, DocumentStatus.CHUNKING.value} and not force:
            connection.rollback()
            return False
        connection.execute(
            """UPDATE documents SET status=?,processing_error=NULL,mineru_result_path=NULL,updated_at=?
            WHERE id=?""",
            (DocumentStatus.SOURCE_SAVED.value,now,document_id),
        )
        connection.commit()
    return True


def queue_chunking(document_id: str) -> bool:
    """使用已有 MinerU 结果重新进入切分阶段。"""
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE documents SET status=?,processing_error=NULL,updated_at=?
            WHERE id=? AND mineru_result_path IS NOT NULL
            AND status IN (?,?,?)""",
            (DocumentStatus.MINERU_PARSED.value,now,document_id,
             DocumentStatus.SUCCEEDED.value,DocumentStatus.CHUNKING_FAILED.value,
             DocumentStatus.MINERU_PARSED.value),
        )
        return connection.total_changes > 0


def claim_next_document() -> dict | None:
    """原子领取一个文档，并把其状态推进到 MinerU 或切分的执行中状态。"""
    now = _now()
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT * FROM documents WHERE status IN (?,?)
            ORDER BY created_at,rowid LIMIT 1""",
            (DocumentStatus.SOURCE_SAVED.value, DocumentStatus.MINERU_PARSED.value),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        next_status = (DocumentStatus.MINERU_PARSING.value
                       if row["status"] == DocumentStatus.SOURCE_SAVED.value
                       else DocumentStatus.CHUNKING.value)
        connection.execute(
            "UPDATE documents SET status=?,processing_error=NULL,updated_at=? WHERE id=? AND status=?",
            (next_status,now,row["id"],row["status"]),
        )
        claimed = dict(row)
        claimed["claimed_status"] = next_status
        connection.commit()
    return claimed


def complete_mineru(document_id: str, result_path: Path) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE documents SET status=?,mineru_result_path=?,processing_error=NULL,updated_at=?
            WHERE id=? AND status=?""",
            (DocumentStatus.MINERU_PARSED.value,str(result_path),_now(),document_id,
             DocumentStatus.MINERU_PARSING.value),
        )


def complete_chunking(document_id: str) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE documents SET status=?,processing_error=NULL,updated_at=?
            WHERE id=? AND status=?""",
            (DocumentStatus.SUCCEEDED.value,_now(),document_id,DocumentStatus.CHUNKING.value),
        )


def fail_processing(document_id: str, active_status: str, error: str) -> None:
    failed_status = (DocumentStatus.MINERU_FAILED.value
                     if active_status == DocumentStatus.MINERU_PARSING.value
                     else DocumentStatus.CHUNKING_FAILED.value)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE documents SET status=?,processing_error=?,updated_at=?
            WHERE id=? AND status=?""",
            (failed_status,error,_now(),document_id,active_status),
        )
