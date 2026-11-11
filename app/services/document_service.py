import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
<<<<<<< HEAD
from app.core.enums import DocumentStatus
=======
from app.core.database import begin_write, connect
from app.core.enums import ParseStepKey, ParseStepStatus
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    """初始化文档表；处理进度只保存在 documents.status。"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
<<<<<<< HEAD
    with sqlite3.connect(settings.database_path) as connection:
=======
    with connect() as connection:
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
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
<<<<<<< HEAD


def recover_interrupted_processing() -> None:
    """服务重启后把处理中断的状态退回到该阶段的入口，让 Worker 重做这一阶段。"""
    with sqlite3.connect(settings.database_path) as connection:
=======
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")} if not settings.database_url else set()
        migrations = {
            "grade": "TEXT NOT NULL DEFAULT '未指定'",
            "unit": "TEXT NOT NULL DEFAULT '未指定'",
            "parsing_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "parse_error": "TEXT",
            "parsed_path": "TEXT",
            "current_task_id": "TEXT",
        }
        for name, definition in migrations.items():
            if settings.database_url:
                connection.execute(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {name} {definition}")
            elif name not in columns:
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
        connection.execute(
            """CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES parse_tasks(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                heading TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                UNIQUE (task_id, chunk_index)
            )"""
        )
        # 兼容曾把切分状态写入解析字段的文档。
        connection.execute(
            """UPDATE documents SET parsing_status='succeeded',parse_error=NULL
            WHERE parsing_status IN ('chunking','chunking_failed') AND parsed_path IS NOT NULL"""
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
            mineru_status = (
                ParseStepStatus.SUCCEEDED.value
                if document["parsed_path"] and document["parsing_status"] == ParseStepStatus.SUCCEEDED.value
                else ParseStepStatus.FAILED.value
                if document["parsing_status"] in {ParseStepStatus.FAILED.value,ParseStepStatus.MINERU_FAILED.value}
                else ParseStepStatus.QUEUED.value
            )
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
                (mineru_status,document["parse_error"],document["parsed_path"],
                 document["updated_at"] if mineru_status in {ParseStepStatus.FAILED.value,ParseStepStatus.SUCCEEDED.value} else None,
                 document["current_task_id"]),
            )
        current_documents = connection.execute(
            """SELECT id,current_task_id,parsed_path FROM documents
            WHERE current_task_id IS NOT NULL"""
        ).fetchall()
        for document in current_documents:
            mineru_step = connection.execute(
                "SELECT status FROM parse_task_steps WHERE task_id=? AND step_key=?",
                (document["current_task_id"],ParseStepKey.MINERU_PARSE.value),
            ).fetchone()
            initial_status = (
                ParseStepStatus.QUEUED.value
                if mineru_step and mineru_step["status"] == ParseStepStatus.SUCCEEDED.value and document["parsed_path"]
                else ParseStepStatus.SKIPPED.value
                if mineru_step and mineru_step["status"] == ParseStepStatus.FAILED.value
                else ParseStepStatus.WAITING.value
            )
            connection.execute(
                """INSERT INTO parse_task_steps
                (id,task_id,document_id,step_key,title,status,input_path,created_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (task_id,step_key) DO NOTHING""",
                (uuid4().hex,document["current_task_id"],document["id"],ParseStepKey.CHUNKING.value,
                 "文本切分",initial_status,document["parsed_path"],_now()),
            )
            if initial_status == ParseStepStatus.QUEUED.value:
                connection.execute(
                    """UPDATE parse_task_steps SET status=?,input_path=?
                    WHERE task_id=? AND step_key=? AND status=?""",
                    (ParseStepStatus.QUEUED.value,document["parsed_path"],document["current_task_id"],
                     ParseStepKey.CHUNKING.value,ParseStepStatus.WAITING.value),
                )
            elif initial_status == ParseStepStatus.SKIPPED.value:
                connection.execute(
                    """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
                    WHERE task_id=? AND step_key=? AND status=?""",
                    (ParseStepStatus.SKIPPED.value,"MinerU 解析失败，未执行切分",_now(),
                     document["current_task_id"],ParseStepKey.CHUNKING.value,ParseStepStatus.WAITING.value),
                )


def recover_interrupted_steps() -> None:
    """Worker 启动时重新排队上次进程中断的步骤。"""
    with connect() as connection:
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        connection.execute(
            "UPDATE documents SET status=?,processing_error=NULL WHERE status=?",
            (DocumentStatus.SOURCE_SAVED.value, DocumentStatus.MINERU_PARSING.value),
        )
        connection.execute(
            "UPDATE documents SET status=?,processing_error=NULL WHERE status=?",
            (DocumentStatus.MINERU_PARSED.value, DocumentStatus.CHUNKING.value),
        )



def _document(row: Mapping) -> dict:
    document = {key: row[key] for key in (
        "id", "title", "grade", "unit", "description", "filename", "stored_name", "file_type",
        "size_bytes", "status", "processing_error", "mineru_result_path", "created_at", "updated_at",
    )}
    document["steps"] = json.loads(row["steps"]) if isinstance(row["steps"], str) else row["steps"]
    return document


_DOCUMENT_QUERY = """
    SELECT doc.*, (
        SELECT json_group_object(step_key, json_object('status', status, 'error', error))
        FROM parse_task_steps WHERE task_id=doc.current_task_id AND document_id=doc.id
    ) AS steps
    FROM documents AS doc
"""

def _document_query() -> str:
    if settings.database_url:
        return _DOCUMENT_QUERY.replace(
            "json_group_object(step_key, json_object('status', status, 'error', error))",
            "COALESCE(json_object_agg(step_key, json_build_object('status', status, 'error', error)), '{}'::json)",
        )
    return _DOCUMENT_QUERY


def list_documents() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(_document_query() + " ORDER BY doc.created_at DESC").fetchall()
    return [_document(row) for row in rows]


def get_document(document_id: str) -> dict | None:
<<<<<<< HEAD
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
=======
    with connect() as connection:
        row = connection.execute(_document_query() + " WHERE doc.id = ?", (document_id,)).fetchone()
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
    return _document(row) if row else None


def get_stored_path(document_id: str) -> Path | None:
<<<<<<< HEAD
    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute("SELECT stored_name FROM documents WHERE id=?", (document_id,)).fetchone()
    return settings.upload_dir / row[0] if row else None
=======
    with connect() as connection:
        row = connection.execute("SELECT stored_name FROM documents WHERE id = ?", (document_id,)).fetchone()
    return settings.upload_dir / row["stored_name"] if row else None
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d


def get_chunks_path(document_id: str) -> Path:
    return settings.parsed_dir / document_id / "chunks.jsonl"


def create_document(document_id: str, title: str, grade: str, unit: str, description: str,
                    filename: str, stored_name: str, file_type: str, size_bytes: int) -> dict:
<<<<<<< HEAD
    now = _now()
    with sqlite3.connect(settings.database_path) as connection:
=======
    now, task_id = _now(), uuid4().hex
    with connect() as connection:
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
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
    with connect() as connection:
        if replacement:
            filename, stored_name, file_type, size_bytes = replacement
            result = connection.execute(
                """UPDATE documents SET title=?,grade=?,unit=?,description=?,filename=?,stored_name=?,file_type=?,size_bytes=?,
                status=?,processing_error=NULL,mineru_result_path=NULL,updated_at=? WHERE id=?""",
                (title,grade,unit,description,filename,stored_name,file_type,size_bytes,
                 DocumentStatus.SOURCE_SAVED.value,now,document_id),
            )
        else:
            result = connection.execute(
                "UPDATE documents SET title=?,grade=?,unit=?,description=?,updated_at=? WHERE id=?",
                (title,grade,unit,description,now,document_id),
            )
        if result.rowcount == 0:
            return None
    return get_document(document_id)


def delete_document(document_id: str) -> tuple[Path, Path] | None:
    document = get_document(document_id)
    if document is None:
        return None
    stored_path = settings.upload_dir / document["stored_name"]
<<<<<<< HEAD
    artifact_dir = settings.parsed_dir / document_id
    with sqlite3.connect(settings.database_path) as connection:
=======
    parsed_path = Path(document["parsed_path"]) if document["parsed_path"] else None
    with connect() as connection:
        begin_write(connection)
        connection.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM parse_tasks WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM parse_task_steps WHERE document_id=?", (document_id,))
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
    return stored_path, artifact_dir


<<<<<<< HEAD
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
=======
def queue_parse(document_id: str, force: bool = False) -> str | None:
    now, task_id = _now(), uuid4().hex
    with connect() as connection:
        begin_write(connection)
        row = connection.execute(
            """SELECT doc.parsing_status,doc.stored_name,doc.current_task_id,task.status AS processing_status
            FROM documents AS doc LEFT JOIN parse_tasks AS task ON task.id=doc.current_task_id
            WHERE doc.id=?""",
            (document_id,),
        ).fetchone()
        active_statuses = {ParseStepStatus.QUEUED.value, ParseStepStatus.PROCESSING.value}
        if row is None:
            return None
        if not force and (
            row["processing_status"] in active_statuses
            or row["parsing_status"] in active_statuses | {
                ParseStepStatus.SOURCE_SAVED.value, ParseStepStatus.MINERU_PARSING.value,
            }
        ):
            return None
        if row["current_task_id"]:
            connection.execute(
                """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
                WHERE task_id=? AND status IN (?,?)""",
                (ParseStepStatus.SKIPPED.value,"任务已被新的解析任务替代",now,row["current_task_id"],
                 ParseStepStatus.QUEUED.value,ParseStepStatus.WAITING.value),
            )
            connection.execute(
                """UPDATE parse_tasks SET status=?,error=?,finished_at=?
                WHERE id=? AND status IN (?,?)""",
                (ParseStepStatus.FAILED.value,"任务已被新的解析任务替代",now,row["current_task_id"],
                 ParseStepStatus.QUEUED.value,ParseStepStatus.PROCESSING.value),
            )
        connection.execute(
            "UPDATE documents SET parsing_status=?,parse_error=NULL,current_task_id=?,parsed_path=NULL,updated_at=? WHERE id=?",
            (ParseStepStatus.SOURCE_SAVED.value,task_id,now,document_id),
        )
        connection.execute(
            "INSERT INTO parse_tasks (id,document_id,status,created_at) VALUES (?,?,?,?)",
            (task_id,document_id,ParseStepStatus.QUEUED.value,now),
        )
        _insert_steps(connection, task_id, document_id, settings.upload_dir / row["stored_name"], now)
    return task_id


def get_task(task_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM parse_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _insert_steps(connection, task_id: str, document_id: str,
                  source_path: Path, now: str) -> None:
    connection.executemany(
        """INSERT INTO parse_task_steps
        (id,task_id,document_id,step_key,title,status,input_path,output_path,created_at,finished_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            (uuid4().hex,task_id,document_id,ParseStepKey.SOURCE_SAVED.value,"原始文件保存",ParseStepStatus.SUCCEEDED.value,
             None,str(source_path),now,now),
            (uuid4().hex,task_id,document_id,ParseStepKey.MINERU_PARSE.value,"MinerU 结构解析",ParseStepStatus.QUEUED.value,
             str(source_path),None,now,None),
            (uuid4().hex,task_id,document_id,ParseStepKey.CHUNKING.value,"文本切分",ParseStepStatus.WAITING.value,
             None,None,now,None),
            *([(uuid4().hex,task_id,document_id,ParseStepKey.EMBEDDING.value,"向量化",
                ParseStepStatus.WAITING.value,None,None,now,None)] if settings.embedding_enabled else []),
        ],
    )


def get_document_steps(document_id: str) -> list[dict]:
    document = get_document(document_id)
    if document is None or not document["current_task_id"]:
        return []
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM parse_task_steps WHERE task_id=? ORDER BY created_at, CASE step_key WHEN 'source_saved' THEN 0 WHEN 'mineru_parse' THEN 1 ELSE 2 END",
            (document["current_task_id"],),
        ).fetchall()
    return [dict(row) for row in rows]


def set_step_status(task_id: str, step_key: str, status: ParseStepStatus, *, error: str | None = None,
                    input_path: Path | None = None, output_path: Path | None = None,
                    details: str | None = None) -> None:
    now = _now()
    status_value = status.value
    with connect() as connection:
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        connection.execute(
            """UPDATE documents SET status=?,processing_error=NULL,updated_at=?
            WHERE id=? AND mineru_result_path IS NOT NULL
            AND status IN (?,?,?)""",
            (DocumentStatus.MINERU_PARSED.value,now,document_id,
             DocumentStatus.SUCCEEDED.value,DocumentStatus.CHUNKING_FAILED.value,
             DocumentStatus.MINERU_PARSED.value),
        )
        return connection.total_changes > 0


<<<<<<< HEAD
def claim_next_document() -> dict | None:
    """原子领取一个文档，并把其状态推进到 MinerU 或切分的执行中状态。"""
=======
def claim_next_step(step_key: ParseStepKey) -> dict | None:
    """以写事务原子领取一个排队步骤，避免多个 Worker 重复执行。"""
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
    now = _now()
    with connect() as connection:
        begin_write(connection)
        row = connection.execute(
<<<<<<< HEAD
            """SELECT * FROM documents WHERE status IN (?,?)
            ORDER BY created_at,rowid LIMIT 1""",
            (DocumentStatus.SOURCE_SAVED.value, DocumentStatus.MINERU_PARSED.value),
=======
            """SELECT step.* FROM parse_task_steps AS step
            JOIN documents AS doc ON doc.id=step.document_id
            WHERE step.status=? AND step.step_key=? AND doc.current_task_id=step.task_id
            ORDER BY step.created_at,step.id LIMIT 1""",
            (ParseStepStatus.QUEUED.value, step_key.value),
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        next_status = (DocumentStatus.MINERU_PARSING.value
                       if row["status"] == DocumentStatus.SOURCE_SAVED.value
                       else DocumentStatus.CHUNKING.value)
        connection.execute(
<<<<<<< HEAD
            "UPDATE documents SET status=?,processing_error=NULL,updated_at=? WHERE id=? AND status=?",
            (next_status,now,row["id"],row["status"]),
        )
=======
            """UPDATE parse_task_steps SET status=?,started_at=?,finished_at=NULL,error=NULL
            WHERE id=? AND status=?""",
            (ParseStepStatus.PROCESSING.value,now,row["id"],ParseStepStatus.QUEUED.value),
        )
        connection.execute(
            """UPDATE parse_tasks SET status=?,started_at=COALESCE(started_at,?),finished_at=NULL,error=NULL
            WHERE id=?""",
            (ParseStepStatus.PROCESSING.value,now,row["task_id"]),
        )
        if row["step_key"] == ParseStepKey.MINERU_PARSE.value:
            connection.execute(
                """UPDATE documents SET parsing_status=?,parse_error=NULL,updated_at=?
                WHERE id=? AND current_task_id=?""",
                (ParseStepStatus.MINERU_PARSING.value,now,row["document_id"],row["task_id"]),
            )
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        claimed = dict(row)
        claimed["claimed_status"] = next_status
        connection.commit()
    return claimed


<<<<<<< HEAD
def complete_mineru(document_id: str, result_path: Path) -> None:
    with sqlite3.connect(settings.database_path) as connection:
=======
def queue_chunking_step(task_id: str, document_id: str, input_path: Path) -> str:
    """将切分步骤排队；可用于已完成解析的旧文档补生成切分。"""
    now = _now()
    with connect() as connection:
        begin_write(connection)
        document = connection.execute(
            "SELECT current_task_id,parsing_status,parsed_path FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        if document is None or document["current_task_id"] != task_id:
            connection.rollback()
            raise ValueError("文档当前解析任务已改变")
        if (document["parsing_status"] != ParseStepStatus.SUCCEEDED.value
                or document["parsed_path"] != str(input_path)):
            raise ValueError("当前任务的 MinerU 解析结果尚未生成")
        step = connection.execute(
            "SELECT * FROM parse_task_steps WHERE task_id=? AND step_key=?",
            (task_id,ParseStepKey.CHUNKING.value),
        ).fetchone()
        if step is None:
            connection.execute(
                """INSERT INTO parse_task_steps
                (id,task_id,document_id,step_key,title,status,input_path,created_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (task_id,step_key) DO NOTHING""",
                (uuid4().hex,task_id,document_id,ParseStepKey.CHUNKING.value,"文本切分",
                 ParseStepStatus.QUEUED.value,str(input_path),now),
            )
        elif (step["status"] == ParseStepStatus.SUCCEEDED.value and json.loads(step["details"] or "{}").get("chunks_in_database")):
            connection.commit()
            return ParseStepStatus.SUCCEEDED.value
        elif step["status"] == ParseStepStatus.PROCESSING.value:
            connection.commit()
            return ParseStepStatus.PROCESSING.value
        else:
            connection.execute(
                """UPDATE parse_task_steps SET status=?,input_path=?,output_path=NULL,error=NULL,
                started_at=NULL,finished_at=NULL WHERE task_id=? AND step_key=?""",
                (ParseStepStatus.QUEUED.value,str(input_path),task_id,ParseStepKey.CHUNKING.value),
            )
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        connection.execute(
            """UPDATE documents SET status=?,mineru_result_path=?,processing_error=NULL,updated_at=?
            WHERE id=? AND status=?""",
            (DocumentStatus.MINERU_PARSED.value,str(result_path),_now(),document_id,
             DocumentStatus.MINERU_PARSING.value),
        )
<<<<<<< HEAD


def complete_chunking(document_id: str) -> None:
    with sqlite3.connect(settings.database_path) as connection:
=======
        connection.commit()
    return ParseStepStatus.QUEUED.value


def complete_mineru_step(task_id: str, document_id: str, parsed_path: Path) -> None:
    """原子完成 MinerU 步骤并把切分步骤转为可领取状态。"""
    now = _now()
    with connect() as connection:
        begin_write(connection)
        current = connection.execute(
            "SELECT 1 FROM documents WHERE id=? AND current_task_id=?", (document_id,task_id)
        ).fetchone()
        if current is None:
            connection.execute(
                """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
                WHERE task_id=? AND step_key=?""",
                (ParseStepStatus.SKIPPED.value,"文档已切换到新的解析任务",now,task_id,ParseStepKey.MINERU_PARSE.value),
            )
            connection.execute(
                """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
                WHERE task_id=? AND status IN (?,?)""",
                (ParseStepStatus.SKIPPED.value,"文档已切换到新的解析任务",now,task_id,
                 ParseStepStatus.QUEUED.value,ParseStepStatus.WAITING.value),
            )
            connection.execute(
                "UPDATE parse_tasks SET status=?,error=?,finished_at=? WHERE id=?",
                (ParseStepStatus.FAILED.value,"文档已切换到新的解析任务",now,task_id),
            )
            connection.commit()
            return
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
        connection.execute(
            """UPDATE documents SET status=?,processing_error=NULL,updated_at=?
            WHERE id=? AND status=?""",
            (DocumentStatus.SUCCEEDED.value,_now(),document_id,DocumentStatus.CHUNKING.value),
        )
<<<<<<< HEAD


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
=======
        connection.execute(
            """UPDATE parse_task_steps SET status=?,input_path=?,error=NULL,started_at=NULL,finished_at=NULL
            WHERE task_id=? AND step_key=? AND status IN (?,?)""",
            (ParseStepStatus.QUEUED.value,str(parsed_path),task_id,ParseStepKey.CHUNKING.value,
             ParseStepStatus.WAITING.value,ParseStepStatus.QUEUED.value),
        )
        connection.execute(
            """UPDATE documents SET parsed_path=?,parsing_status=?,parse_error=NULL,updated_at=?
            WHERE id=? AND current_task_id=?""",
            (str(parsed_path),ParseStepStatus.SUCCEEDED.value,now,document_id,task_id),
        )
        connection.execute(
            "UPDATE parse_tasks SET status=?,error=NULL WHERE id=?",
            (ParseStepStatus.QUEUED.value,task_id),
        )
        connection.commit()


def read_chunking_result(step: dict | None) -> list[dict] | None:
    if not step or step["status"] != ParseStepStatus.SUCCEEDED.value:
        return None
    with connect() as connection:
        rows = connection.execute(
            """SELECT chunk_index,text,heading,char_count,metadata FROM document_chunks
            WHERE task_id=? AND document_id=? ORDER BY chunk_index""",
            (step["task_id"], step["document_id"]),
        ).fetchall()
    if rows:
        return [
            {**dict(row), "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]}
            for row in rows
        ]
    if json.loads(step["details"] or "{}").get("chunks_in_database"):
        return []
    return None


def migrate_chunk_files() -> int:
    """先提交旧切分块，再清理数据库已收录的 JSONL。"""
    imported = []
    with connect() as connection:
        begin_write(connection)
        steps = connection.execute(
            """SELECT step.* FROM parse_task_steps AS step
            JOIN parse_tasks AS task ON task.id=step.task_id
            JOIN documents AS doc ON doc.id=step.document_id
            WHERE step.step_key=? AND step.status=? AND step.output_path IS NOT NULL""",
            (ParseStepKey.CHUNKING.value, ParseStepStatus.SUCCEEDED.value),
        ).fetchall()
        for step in steps:
            path = Path(step["output_path"])
            expected = settings.parsed_dir.resolve() / step["task_id"] / "chunks.jsonl"
            if not expected.is_relative_to(settings.parsed_dir.resolve()) or path.resolve() != expected or not path.is_file():
                continue
            with path.open(encoding="utf-8") as source:
                chunks = [json.loads(line) for line in source if line.strip()]
            details = json.loads(step["details"] or "{}")
            if details.get("chunks_in_database"):
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM document_chunks WHERE task_id=?", (step["task_id"],)
                ).fetchone()["count"]
                if count != len(chunks):
                    continue
            else:
                _store_chunks(connection, step["task_id"], step["document_id"], chunks)
                details.update(chunk_count=len(chunks), chunks_in_database=True)
                connection.execute(
                    "UPDATE parse_task_steps SET details=? WHERE id=?", (json.dumps(details), step["id"])
                )
            imported.append((step["id"], path))
    for step_id, path in imported:
        path.unlink(missing_ok=True)
        with connect() as connection:
            connection.execute("UPDATE parse_task_steps SET output_path=NULL WHERE id=? AND output_path=?",
                               (step_id, str(path)))
    return len(imported)


def _store_chunks(connection, task_id: str, document_id: str, chunks: list[dict]) -> None:
    connection.execute("DELETE FROM document_chunks WHERE task_id=?", (task_id,))
    connection.executemany(
        """INSERT INTO document_chunks
        (chunk_id,document_id,task_id,chunk_index,text,heading,char_count,metadata)
        VALUES (?,?,?,?,?,?,?,?)""",
        [
            (f"{task_id}:{chunk['chunk_index']}", document_id, task_id, chunk["chunk_index"],
             chunk["text"], chunk["heading"], chunk["char_count"],
             json.dumps(chunk["metadata"], ensure_ascii=False))
            for chunk in chunks
        ],
    )


def complete_chunking_step(task_id: str, document_id: str,
                           *, chunks: list[dict]) -> None:
    """原子完成切分步骤及整个文档处理任务。"""
    now = _now()
    with connect() as connection:
        begin_write(connection)
        current = connection.execute(
            """SELECT 1 FROM documents AS doc JOIN parse_task_steps AS step
            ON step.task_id=doc.current_task_id AND step.document_id=doc.id
            WHERE doc.id=? AND step.task_id=? AND step.step_key=? AND step.status=?""",
            (document_id, task_id, ParseStepKey.CHUNKING.value, ParseStepStatus.PROCESSING.value),
        ).fetchone()
        if current is None:
            return
        _store_chunks(connection, task_id, document_id, chunks)
        details = json.dumps({"chunk_count": len(chunks), "chunks_in_database": True})
        connection.execute(
            """UPDATE parse_task_steps SET status=?,output_path=?,details=COALESCE(?,details),error=NULL,finished_at=?
            WHERE task_id=? AND step_key=?""",
            (ParseStepStatus.SUCCEEDED.value,None,details,now,task_id,ParseStepKey.CHUNKING.value),
        )
        if settings.embedding_enabled:
            _queue_embedding(connection, task_id, document_id)
        else:
            connection.execute(
                "UPDATE parse_tasks SET status=?,error=NULL,finished_at=? WHERE id=?",
                (ParseStepStatus.SUCCEEDED.value,now,task_id),
            )
        connection.commit()


def _queue_embedding(connection, task_id: str, document_id: str) -> None:
    connection.execute(
        """INSERT INTO parse_task_steps (id,task_id,document_id,step_key,title,status,created_at)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT (task_id,step_key) DO UPDATE
        SET status=excluded.status,error=NULL,started_at=NULL,finished_at=NULL,details=NULL""",
        (uuid4().hex,task_id,document_id,ParseStepKey.EMBEDDING.value,"向量化",ParseStepStatus.QUEUED.value,_now()),
    )
    connection.execute("UPDATE parse_tasks SET status=?,error=NULL,finished_at=NULL WHERE id=?",
                       (ParseStepStatus.QUEUED.value,task_id))


def queue_existing_embeddings() -> None:
    with connect() as connection:
        begin_write(connection)
        steps = connection.execute(
            """SELECT chunk.task_id,chunk.document_id FROM parse_task_steps AS chunk
            JOIN documents AS doc ON doc.id=chunk.document_id AND doc.current_task_id=chunk.task_id
            WHERE chunk.step_key=? AND chunk.status=? AND NOT EXISTS (
                SELECT 1 FROM parse_task_steps AS embedding WHERE embedding.task_id=chunk.task_id
                AND embedding.step_key=? AND embedding.status!=?
            )""",
            (ParseStepKey.CHUNKING.value,ParseStepStatus.SUCCEEDED.value,
             ParseStepKey.EMBEDDING.value,ParseStepStatus.WAITING.value),
        ).fetchall()
        for step in steps:
            _queue_embedding(connection, step["task_id"], step["document_id"])


def retry_embedding(document_id: str) -> bool:
    with connect() as connection:
        begin_write(connection)
        step = connection.execute(
            """SELECT step.task_id FROM parse_task_steps AS step
            JOIN documents AS doc ON doc.id=step.document_id AND doc.current_task_id=step.task_id
            WHERE doc.id=? AND step.step_key=? AND step.status=?""",
            (document_id,ParseStepKey.EMBEDDING.value,ParseStepStatus.FAILED.value),
        ).fetchone()
        if step is None:
            return False
        _queue_embedding(connection, step["task_id"], document_id)
        return True


def get_embedding_chunks(task_id: str, document_id: str) -> list[dict]:
    with connect() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT chunk_id,text FROM document_chunks
            WHERE task_id=? AND document_id=? ORDER BY chunk_index""",
            (task_id,document_id),
        ).fetchall()]


def complete_embedding_step(task_id: str, document_id: str, count: int) -> None:
    with connect() as connection:
        begin_write(connection)
        now = _now()
        updated = connection.execute(
            """UPDATE parse_task_steps SET status=?,details=?,error=NULL,finished_at=?
            WHERE task_id=? AND document_id=? AND step_key=? AND status=? AND EXISTS (
                SELECT 1 FROM documents WHERE id=? AND current_task_id=?
            )""",
            (ParseStepStatus.SUCCEEDED.value,json.dumps({"vector_count": count}),now,
             task_id,document_id,ParseStepKey.EMBEDDING.value,ParseStepStatus.PROCESSING.value,document_id,task_id),
        )
        if updated.rowcount:
            connection.execute("UPDATE parse_tasks SET status=?,error=NULL,finished_at=? WHERE id=?",
                               (ParseStepStatus.SUCCEEDED.value,now,task_id))


def fail_step(task_id: str, document_id: str, step_key: str, error: str) -> None:
    """失败时终止当前任务并跳过所有依赖步骤。"""
    now = _now()
    document_status = {
        ParseStepKey.MINERU_PARSE.value: ParseStepStatus.MINERU_FAILED.value,
        ParseStepKey.SOURCE_SAVED.value: ParseStepStatus.SOURCE_SAVE_FAILED.value,
    }.get(step_key, ParseStepStatus.FAILED.value)
    with connect() as connection:
        begin_write(connection)
        connection.execute(
            """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
            WHERE task_id=? AND step_key=?""",
            (ParseStepStatus.FAILED.value,error,now,task_id,step_key),
        )
        connection.execute(
            """UPDATE parse_task_steps SET status=?,error=?,finished_at=?
            WHERE task_id=? AND status IN (?,?)""",
            (ParseStepStatus.SKIPPED.value,"上游步骤失败，未执行",now,task_id,
             ParseStepStatus.QUEUED.value,ParseStepStatus.WAITING.value),
        )
        connection.execute(
            "UPDATE parse_tasks SET status=?,error=?,finished_at=? WHERE id=?",
            (ParseStepStatus.FAILED.value,error,now,task_id),
        )
        if step_key in {ParseStepKey.MINERU_PARSE.value, ParseStepKey.SOURCE_SAVED.value}:
            connection.execute(
                """UPDATE documents SET parsing_status=?,parse_error=?,updated_at=?
                WHERE id=? AND current_task_id=?""",
                (document_status,error,now,document_id,task_id),
            )
        connection.commit()
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
