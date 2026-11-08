import json
import time
import traceback
from threading import Event
from pathlib import Path

from app.core.config import settings
from app.core.enums import ParseStepKey, ParseStepStatus
from app.services import document_service
from app.services.chunking_service import create_chunks
from app.services.embedding_service import embed_chunks
from app.services.parsing_service import parse_with_mineru


def _process_mineru_step(step: dict) -> None:
    source = Path(step["input_path"]) if step["input_path"] else document_service.get_stored_path(step["document_id"])
    if source is None or not source.is_file():
        raise FileNotFoundError("原始文件不存在")
    parsed_path = parse_with_mineru(source, step["task_id"])
    document_service.complete_mineru_step(step["task_id"], step["document_id"], parsed_path)


def _process_chunking_step(step: dict) -> None:
    document = document_service.get_document(step["document_id"])
    if document is None:
        raise FileNotFoundError("文档记录不存在")
    source = Path(step["input_path"]) if step["input_path"] else (
        Path(document["parsed_path"]) if document["parsed_path"] else None
    )
    if source is None or not source.is_file():
        raise FileNotFoundError("MinerU Markdown 解析结果不存在")
    chunks = create_chunks(source, document)
    document_service.complete_chunking_step(step["task_id"], step["document_id"], chunks=chunks,
    )


def process_next_step(step_key: ParseStepKey) -> bool:
    """领取并处理一个排队步骤；没有任务时返回 False。"""
    step = document_service.claim_next_step(step_key)
    if step is None:
        return False
    try:
        if step["step_key"] == ParseStepKey.MINERU_PARSE.value:
            _process_mineru_step(step)
        elif step["step_key"] == ParseStepKey.CHUNKING.value:
            _process_chunking_step(step)
        elif step["step_key"] == ParseStepKey.EMBEDDING.value:
            task_id, document_id = step["task_id"], step["document_id"]
            chunks = document_service.get_embedding_chunks(task_id, document_id)
            count = embed_chunks(chunks, document_id, task_id)
            document_service.complete_embedding_step(task_id, document_id, count)
        else:
            raise ValueError(f"Worker 不支持此步骤：{step['step_key']}")
    except Exception as error:
        task_dir = settings.parsed_dir / step["task_id"]
        task_dir.mkdir(parents=True, exist_ok=True)
        error_path = task_dir / f"{step['step_key']}.error.txt"
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        document_service.set_step_status(
            step["task_id"], step["step_key"],
            # 失败状态由 fail_step 原子写入；这里仅保存错误文件路径。
            ParseStepStatus.PROCESSING,
            details=json.dumps({"error_file": str(error_path)}, ensure_ascii=False),
        )
        document_service.fail_step(
            step["task_id"], step["document_id"], step["step_key"], str(error),
        )
        print(f"步骤失败：{step['step_key']}，文档 {step['document_id']}：{error}", flush=True)
    else:
        print(f"步骤完成：{step['step_key']}，文档 {step['document_id']}", flush=True)
    return True


def run_worker(stop_event: Event, step_key: ParseStepKey) -> None:
    """持续轮询数据库队列；收到停止信号后在当前步骤结束后退出。"""
    print(f"文档处理 Worker [{step_key.value}] 已启动", flush=True)
    while not stop_event.is_set():
        try:
            processed = process_next_step(step_key)
        except Exception as error:
            print(f"Worker 发生异常：{error}", flush=True)
            processed = False
        if not processed:
            stop_event.wait(max(0.2, settings.worker_poll_interval_seconds))
