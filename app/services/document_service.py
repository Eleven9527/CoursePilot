import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.enums import ParseStepStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                grade TEXT NOT NULL DEFAULT '未指定', unit TEXT NOT NULL DEFAULT '未指定', description TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL, stored_name TEXT NOT NULL, file_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, parsing_status TEXT NOT NULL DEFAULT 'not_started',
                parse_error TEXT, parsed_path TEXT, current_task_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
        migrations = {
            "grade": "TEXT NOT NULL DEFAULT '未指定'",
            "unit": "TEXT NOT NULL DEFAULT '未指定'",
            "parsing_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "parse_error": "TEXT",
            "parsed_path": "TEXT",
            "current_task_id": "TEXT",
        }
        for name, definition in migrations.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        connection.execute(
            """UPDATE documents SET grade = '未指定'
            WHERE grade IN ('本科一年级','本科二年级','本科三年级','本科四年级','研究生','其他')"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS parse_tasks (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS parse_task_steps (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document_id TEXT NOT NULL,
                step_key TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                input_path TEXT, output_path TEXT, error TEXT, details TEXT,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
            )"""
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_parse_task_steps_task_key ON parse_task_steps(task_id,step_key)"
        )
        # 服务重启后，将中断的任务标记为失败，避免一直显示为运行中。
        connection.execute(
            "UPDATE parse_tasks SET status='failed', error='服务重启，任务中断', finished_at=? WHERE status IN ('queued','processing')",
            (_now(),),
        )
        connection.execute(
            """UPDATE documents SET parsing_status=?, parse_error='服务重启，任务中断'
            WHERE parsing_status IN ('queued','processing','source_saved','mineru_parsing','chunking')""",
            (ParseStepStatus.FAILED.value,),
        )
        legacy_documents = connection.execute(
            """SELECT id,current_task_id,stored_name,parsing_status,parse_error,parsed_path,updated_at
            FROM documents WHERE current_task_id IS NOT NULL"""
        ).fetchall()
        for document in legacy_documents:
            existing_steps = connection.execute(
                "SELECT 1 FROM parse_task_steps WHERE task_id=? LIMIT 1", (document["current_task_id"],)
            ).fetchone()
            if existing_steps:
                continue
            _insert_steps(
                connection,
                document["current_task_id"],
                document["id"],
                settings.upload_dir / document["stored_name"],
                document["updated_at"],
            )
            connection.execute(
                """UPDATE parse_task_steps SET status=?,error=?,output_path=?,finished_at=?
                WHERE task_id=? AND step_key='mineru_parse'""",
                (document["parsing_status"],document["parse_error"],document["parsed_path"],
                 document["updated_at"] if document["parsing_status"] in {ParseStepStatus.FAILED.value,ParseStepStatus.SUCCEEDED.value} else None,
                 document["current_task_id"]),
            )


def _document(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in (
        "id", "title", "grade", "unit", "description", "filename", "stored_name", "file_type",
        "size_bytes", "parsing_status", "parse_error", "parsed_path", "current_task_id",
        "created_at", "updated_at",
    )}


def list_documents() -> list[dict]:
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [_document(row) for row in rows]


def get_document(document_id: str) -> dict | None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return _document(row) if row else None


def get_stored_path(document_id: str) -> Path | None:
    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute("SELECT stored_name FROM documents WHERE id = ?", (document_id,)).fetchone()
    return settings.upload_dir / row[0] if row else None


def create_document(document_id: str, title: str, grade: str, unit: str, description: str,
                    filename: str, stored_name: str, file_type: str, size_bytes: int) -> dict:
    now, task_id = _now(), uuid4().hex
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """INSERT INTO documents
            (id,title,grade,unit,description,filename,stored_name,file_type,size_bytes,parsing_status,current_task_id,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (document_id,title,grade,unit,description,filename,stored_name,file_type,size_bytes,
             ParseStepStatus.SOURCE_SAVED.value,task_id,now,now),
        )
        connection.execute(
            "INSERT INTO parse_tasks (id,document_id,status,created_at) VALUES (?,?,?,?)",
            (task_id,document_id,ParseStepStatus.QUEUED.value,now),
        )
        _insert_steps(connection, task_id, document_id, settings.upload_dir / stored_name, now)
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
                parsing_status=?,parse_error=NULL,parsed_path=NULL,updated_at=? WHERE id=?""",
                (title,grade,unit,description,filename,stored_name,file_type,size_bytes,
                 ParseStepStatus.SOURCE_SAVED.value,now,document_id),
            )
        else:
            connection.execute(
                "UPDATE documents SET title=?,grade=?,unit=?,description=?,updated_at=? WHERE id=?",
                (title,grade,unit,description,now,document_id),
            )
        if connection.total_changes == 0:
            return None
    return get_document(document_id)


def delete_document(document_id: str) -> tuple[Path, Path | None] | None:
    document = get_document(document_id)
    if document is None:
        return None
    stored_path = settings.upload_dir / document["stored_name"]
    parsed_path = Path(document["parsed_path"]) if document["parsed_path"] else None
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("DELETE FROM parse_tasks WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM parse_task_steps WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
    return stored_path, parsed_path


def queue_parse(document_id: str, force: bool = False) -> str | None:
    now, task_id = _now(), uuid4().hex
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT parsing_status,stored_name FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None or (row["parsing_status"] in {
            ParseStepStatus.QUEUED.value, ParseStepStatus.PROCESSING.value,
            ParseStepStatus.SOURCE_SAVED.value, ParseStepStatus.MINERU_PARSING.value,
            ParseStepStatus.CHUNKING.value,
        } and not force):
            return None
        connection.execute(
            "UPDATE documents SET parsing_status=?,parse_error=NULL,current_task_id=?,updated_at=? WHERE id=?",
            (ParseStepStatus.SOURCE_SAVED.value,task_id,now,document_id),
        )
        connection.execute(
            "INSERT INTO parse_tasks (id,document_id,status,created_at) VALUES (?,?,?,?)",
            (task_id,document_id,ParseStepStatus.QUEUED.value,now),
        )
        _insert_steps(connection, task_id, document_id, settings.upload_dir / row["stored_name"], now)
    return task_id


def get_task(task_id: str) -> dict | None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM parse_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _insert_steps(connection: sqlite3.Connection, task_id: str, document_id: str,
                  source_path: Path, now: str) -> None:
    connection.executemany(
        """INSERT INTO parse_task_steps
        (id,task_id,document_id,step_key,title,status,input_path,output_path,created_at,finished_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            (uuid4().hex,task_id,document_id,"source_saved","原始文件保存",ParseStepStatus.SUCCEEDED.value,
             None,str(source_path),now,now),
            (uuid4().hex,task_id,document_id,"mineru_parse","MinerU 结构解析",ParseStepStatus.QUEUED.value,
             str(source_path),None,now,None),
            (uuid4().hex,task_id,document_id,"chunking","文本切分",ParseStepStatus.QUEUED.value,
             None,None,now,None),
        ],
    )


def get_document_steps(document_id: str) -> list[dict]:
    document = get_document(document_id)
    if document is None or not document["current_task_id"]:
        return []
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM parse_task_steps WHERE task_id=? ORDER BY created_at, rowid",
            (document["current_task_id"],),
        ).fetchall()
    return [dict(row) for row in rows]


def set_step_status(task_id: str, step_key: str, status: ParseStepStatus, *, error: str | None = None,
                    input_path: Path | None = None, output_path: Path | None = None,
                    details: str | None = None) -> None:
    now = _now()
    status_value = status.value
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE parse_task_steps SET status=?,error=?,input_path=COALESCE(?,input_path),
            output_path=COALESCE(?,output_path),details=COALESCE(?,details),
            started_at=CASE WHEN ?=? THEN ? ELSE started_at END,
            finished_at=CASE WHEN ? IN (?,?) THEN ? ELSE finished_at END
            WHERE task_id=? AND step_key=?""",
            (status_value,error,str(input_path) if input_path else None,str(output_path) if output_path else None,
             details,status_value,ParseStepStatus.PROCESSING.value,now,
             status_value,ParseStepStatus.SUCCEEDED.value,ParseStepStatus.FAILED.value,now,task_id,step_key),
        )


def ensure_chunking_step(task_id: str, document_id: str, input_path: Path) -> None:
    """为旧解析任务补建切分步骤，重复调用不会创建重复记录。"""
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO parse_task_steps
            (id,task_id,document_id,step_key,title,status,input_path,created_at)
            VALUES (?,?,?,'chunking','文本切分','queued',?,?)""",
            (uuid4().hex,task_id,document_id,str(input_path),_now()),
        )


def mark_processing(task_id: str, document_id: str) -> bool:
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
        cursor = connection.execute(
            "UPDATE documents SET parsing_status=?,parse_error=NULL,updated_at=? WHERE id=? AND current_task_id=?",
            (ParseStepStatus.MINERU_PARSING.value,now,document_id,task_id),
        )
        if cursor.rowcount == 0:
            return False
        connection.execute("UPDATE parse_tasks SET status=?,started_at=? WHERE id=?", (ParseStepStatus.PROCESSING.value,now,task_id))
    return True


def set_document_parse_status(task_id: str, document_id: str, status: ParseStepStatus) -> None:
    """更新文档当前所处的解析阶段。"""
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE documents SET parsing_status=?,updated_at=? WHERE id=? AND current_task_id=?",
            (status.value,_now(),document_id,task_id),
        )


def finish_task(task_id: str, document_id: str, status: ParseStepStatus, error: str | None = None,
                parsed_path: Path | None = None,
                document_status: ParseStepStatus | None = None) -> None:
    now = _now()
    document_status_value = (document_status or status).value
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE parse_tasks SET status=?,error=?,finished_at=? WHERE id=?",
            (status.value,error,now,task_id),
        )
        connection.execute(
            """UPDATE documents SET parsing_status=?,parse_error=?,parsed_path=?,updated_at=?
            WHERE id=? AND current_task_id=?""",
            (document_status_value,error,str(parsed_path) if parsed_path else None,now,document_id,task_id),
        )
