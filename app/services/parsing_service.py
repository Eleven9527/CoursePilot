import json
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.core.enums import ParseStepKey, ParseStepStatus
from app.services import document_service


def parse_with_mineru(source: Path, task_id: str) -> Path:
    """调用本地 MinerU，将输入文档解析为 Markdown。"""
    executable = None
    if settings.mineru_executable:
        executable = shutil.which(settings.mineru_executable)
        if executable is None and Path(settings.mineru_executable).is_file():
            executable = settings.mineru_executable
    else:
        executable = shutil.which("mineru")
    if executable is None and not settings.mineru_executable:
        local_executable = Path(sys.executable).with_name("mineru.exe" if sys.platform == "win32" else "mineru")
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
    command = [
        executable, "parse", str(source), "--tier", tier,
        "--wait", str(settings.mineru_timeout_seconds), "-o", str(output_file),
    ]
    if source.suffix.lower() == ".pdf":
        command.extend(["--pages", "all"])

    document_service.set_step_status(
        task_id,
        ParseStepKey.MINERU_PARSE.value,
        ParseStepStatus.PROCESSING,
        input_path=source,
        details=json.dumps(
            {"command": command, "stdout_log": str(stdout_file), "stderr_log": str(stderr_file)},
            ensure_ascii=False,
        ),
    )
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
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "MinerU 解析失败").strip()
        raise RuntimeError(detail[-1500:])
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError("MinerU 命令已结束，但没有生成 Markdown 解析结果。")
    return output_file
