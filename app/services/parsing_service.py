import shutil
import subprocess
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.core.enums import ParseStepStatus
from app.services import document_service
from app.services.chunking_service import create_chunks


def _parse_with_mineru(source: Path, task_id: str) -> Path:
    executable = None
    if settings.mineru_executable:
        executable = shutil.which(settings.mineru_executable)
        if executable is None and Path(settings.mineru_executable).is_file():
            executable = settings.mineru_executable
    else:
        executable = shutil.which("mineru")
    if executable is None and not settings.mineru_executable:
        local_executable = Path(sys.executable).with_name("mineru.exe")
        if local_executable.is_file():
            executable = str(local_executable)
    if executable is None:
        raise RuntimeError("未检测到 MinerU 命令。请安装 MinerU，或在 .env 中配置有效的 MINERU_EXECUTABLE。")

    output_dir = settings.parsed_dir / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{source.stem}.md"
    stdout_file = output_dir / "mineru.stdout.log"
    stderr_file = output_dir / "mineru.stderr.log"
    tier = settings.mineru_tier_pdf if source.suffix.lower() == ".pdf" else settings.mineru_tier_non_pdf
    command = [executable, "parse", str(source), "--tier", tier, "--wait", str(settings.mineru_timeout_seconds), "-o", str(output_file)]
    if source.suffix.lower() == ".pdf":
        command.extend(["--pages", "all"])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=settings.mineru_timeout_seconds,
        check=False,
    )
    stdout_file.write_text(result.stdout or "", encoding="utf-8")
    stderr_file.write_text(result.stderr or "", encoding="utf-8")
    document_service.set_step_status(
        task_id, "mineru_parse", ParseStepStatus.PROCESSING,
        details=json.dumps({"command": command, "stdout_log": str(stdout_file), "stderr_log": str(stderr_file)}, ensure_ascii=False),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "MinerU 解析失败").strip()
        raise RuntimeError(detail[-1500:])
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError("MinerU 命令已结束，但没有生成 Markdown 解析结果。")
    return output_file


def run_parse_task(task_id: str, document_id: str) -> None:
    if not document_service.mark_processing(task_id, document_id):
        return
    source = document_service.get_stored_path(document_id)
    if source is None or not source.is_file():
        document_service.set_step_status(task_id, "mineru_parse", ParseStepStatus.FAILED, error="原始文件不存在")
        document_service.set_step_status(task_id, "chunking", ParseStepStatus.FAILED, error="原始文件不存在，未执行切分")
        document_service.finish_task(
            task_id, document_id, ParseStepStatus.FAILED, "原始文件不存在",
            document_status=ParseStepStatus.SOURCE_SAVE_FAILED,
        )
        return
    document_service.set_step_status(task_id, "mineru_parse", ParseStepStatus.PROCESSING, input_path=source)
    try:
        parsed_path = _parse_with_mineru(source, task_id)
    except Exception as error:
        details = None
        task_dir = settings.parsed_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "error.txt").write_text(str(error), encoding="utf-8")
        details = json.dumps({"error_file": str(task_dir / "error.txt")}, ensure_ascii=False)
        document_service.set_step_status(
            task_id, "mineru_parse", ParseStepStatus.FAILED, error=str(error), details=details,
        )
        document_service.set_step_status(task_id, "chunking", ParseStepStatus.FAILED, error="MinerU 解析失败，未执行切分")
        document_service.finish_task(
            task_id, document_id, ParseStepStatus.FAILED, str(error),
            document_status=ParseStepStatus.MINERU_FAILED,
        )
        return
    document_service.set_step_status(
        task_id, "mineru_parse", ParseStepStatus.SUCCEEDED, output_path=parsed_path,
    )
    document_service.set_document_parse_status(task_id, document_id, ParseStepStatus.CHUNKING)
    document = document_service.get_document(document_id)
    if document is None:
        document_service.set_step_status(task_id, "chunking", ParseStepStatus.FAILED, error="文档记录不存在，无法生成切分结果")
        document_service.finish_task(
            task_id, document_id, ParseStepStatus.FAILED, "文档记录不存在", parsed_path=parsed_path,
            document_status=ParseStepStatus.CHUNKING_FAILED,
        )
        return
    document_service.set_step_status(task_id, "chunking", ParseStepStatus.PROCESSING, input_path=parsed_path)
    try:
        chunks_path = create_chunks(parsed_path, document, task_id)
    except Exception as error:
        details = json.dumps({"error": str(error)}, ensure_ascii=False)
        document_service.set_step_status(
            task_id, "chunking", ParseStepStatus.FAILED, error=str(error), details=details,
        )
        document_service.finish_task(
            task_id, document_id, ParseStepStatus.FAILED, str(error), parsed_path=parsed_path,
            document_status=ParseStepStatus.CHUNKING_FAILED,
        )
        return
    with chunks_path.open(encoding="utf-8") as chunk_file:
        chunk_count = sum(1 for _ in chunk_file)
    document_service.set_step_status(
        task_id, "chunking", ParseStepStatus.SUCCEEDED, output_path=chunks_path,
        details=json.dumps({"chunk_count": chunk_count}, ensure_ascii=False),
    )
    document_service.finish_task(task_id, document_id, ParseStepStatus.SUCCEEDED, parsed_path=parsed_path)
