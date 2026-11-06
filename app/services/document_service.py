import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.enums import ParseStepKey, ParseStepStatus


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
                """INSERT OR IGNORE INTO parse_task_steps
                (id,task_id,document_id,step_key,title,status,input_path,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
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
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """UPDATE parse_task_steps SET status=?,started_at=NULL,error=NULL
            WHERE status=?""",
            (ParseStepStatus.QUEUED.value,ParseStepStatus.PROCESSING.value),
        )
        connection.execute(
            """UPDATE parse_tasks SET status=?,started_at=NULL,error=NULL
            WHERE status=? AND id IN (SELECT task_id FROM parse_task_steps WHERE status=?)""",
            (ParseStepStatus.QUEUED.value,ParseStepStatus.PROCESSING.value,ParseStepStatus.QUEUED.value),
        )
        connection.execute(
            """UPDATE parse_task_steps SET status=?
            WHERE step_key=? AND status=? AND EXISTS (
                SELECT 1 FROM parse_task_steps AS mineru
                WHERE mineru.task_id=parse_task_steps.task_id AND mineru.step_key=? AND mineru.status!=?
            )""",
            (ParseStepStatus.WAITING.value,ParseStepKey.CHUNKING.value,ParseStepStatus.QUEUED.value,
             ParseStepKey.MINERU_PARSE.value,ParseStepStatus.SUCCEEDED.value),
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
        connection.execute("BEGIN IMMEDIATE")
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
            (uuid4().hex,task_id,document_id,ParseStepKey.SOURCE_SAVED.value,"原始文件保存",ParseStepStatus.SUCCEEDED.value,
             None,str(source_path),now,now),
            (uuid4().hex,task_id,document_id,ParseStepKey.MINERU_PARSE.value,"MinerU 结构解析",ParseStepStatus.QUEUED.value,
             str(source_path),None,now,None),
            (uuid4().hex,task_id,document_id,ParseStepKey.CHUNKING.value,"文本切分",ParseStepStatus.WAITING.value,
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
            finished_at=CASE WHEN ? IN (?,?,?) THEN ? ELSE finished_at END
            WHERE task_id=? AND step_key=?""",
            (status_value,error,str(input_path) if input_path else None,str(output_path) if output_path else None,
             details,status_value,ParseStepStatus.PROCESSING.value,now,
             status_value,ParseStepStatus.SUCCEEDED.value,ParseStepStatus.FAILED.value,
             ParseStepStatus.SKIPPED.value,now,task_id,step_key),
        )


def claim_next_step() -> dict | None:
    """以写事务原子领取一个排队步骤，避免多个 Worker 重复执行。"""
    now = _now()
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT step.* FROM parse_task_steps AS step
            JOIN documents AS doc ON doc.id=step.document_id
            WHERE step.status=? AND doc.current_task_id=step.task_id
            ORDER BY step.created_at,step.rowid LIMIT 1""",
            (ParseStepStatus.QUEUED.value,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
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
        claimed = dict(row)
        connection.commit()
    return claimed


def queue_chunking_step(task_id: str, document_id: str, input_path: Path) -> str:
    """将切分步骤排队；可用于已完成解析的旧文档补生成切分。"""
    now = _now()
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
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
            "SELECT status,output_path FROM parse_task_steps WHERE task_id=? AND step_key=?",
            (task_id,ParseStepKey.CHUNKING.value),
        ).fetchone()
        if step is None:
            connection.execute(
                """INSERT INTO parse_task_steps
                (id,task_id,document_id,step_key,title,status,input_path,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (uuid4().hex,task_id,document_id,ParseStepKey.CHUNKING.value,"文本切分",
                 ParseStepStatus.QUEUED.value,str(input_path),now),
            )
        elif (step["status"] == ParseStepStatus.SUCCEEDED.value and step["output_path"]
              and Path(step["output_path"]).is_file()):
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
        connection.execute(
            """UPDATE parse_tasks SET status=?,error=NULL,started_at=NULL,finished_at=NULL WHERE id=?""",
            (ParseStepStatus.QUEUED.value,task_id),
        )
        connection.commit()
    return ParseStepStatus.QUEUED.value


def complete_mineru_step(task_id: str, document_id: str, parsed_path: Path) -> None:
    """原子完成 MinerU 步骤并把切分步骤转为可领取状态。"""
    now = _now()
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
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
        connection.execute(
            """UPDATE parse_task_steps SET status=?,output_path=?,error=NULL,finished_at=?
            WHERE task_id=? AND step_key=?""",
            (ParseStepStatus.SUCCEEDED.value,str(parsed_path),now,task_id,ParseStepKey.MINERU_PARSE.value),
        )
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


def complete_chunking_step(task_id: str, document_id: str, chunks_path: Path,
                           *, details: str | None = None) -> None:
    """原子完成切分步骤及整个文档处理任务。"""
    now = _now()
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE parse_task_steps SET status=?,output_path=?,details=COALESCE(?,details),error=NULL,finished_at=?
            WHERE task_id=? AND step_key=?""",
            (ParseStepStatus.SUCCEEDED.value,str(chunks_path),details,now,task_id,ParseStepKey.CHUNKING.value),
        )
        connection.execute(
            "UPDATE parse_tasks SET status=?,error=NULL,finished_at=? WHERE id=?",
            (ParseStepStatus.SUCCEEDED.value,now,task_id),
        )
        connection.commit()


def fail_step(task_id: str, document_id: str, step_key: str, error: str) -> None:
    """失败时终止当前任务并跳过所有依赖步骤。"""
    now = _now()
    document_status = {
        ParseStepKey.MINERU_PARSE.value: ParseStepStatus.MINERU_FAILED.value,
        ParseStepKey.SOURCE_SAVED.value: ParseStepStatus.SOURCE_SAVE_FAILED.value,
    }.get(step_key, ParseStepStatus.FAILED.value)
    with sqlite3.connect(settings.database_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
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
        if step_key != ParseStepKey.CHUNKING.value:
            connection.execute(
                """UPDATE documents SET parsing_status=?,parse_error=?,updated_at=?
                WHERE id=? AND current_task_id=?""",
                (document_status,error,now,document_id,task_id),
            )
        connection.commit()
