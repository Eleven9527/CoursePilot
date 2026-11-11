import traceback
from pathlib import Path
from threading import Event

from app.core.config import settings
from app.core.enums import DocumentStatus
from app.services import document_service
from app.services.chunking_service import create_chunks
from app.services.parsing_service import parse_with_mineru


def process_next_document() -> bool:
    """根据 documents.status 领取并推进一个文档的当前处理阶段。"""
    document = document_service.claim_next_document()
    if document is None:
        return False
    document_id = document["id"]
    active_status = document["claimed_status"]
    try:
        if active_status == DocumentStatus.MINERU_PARSING.value:
            source = document_service.get_stored_path(document_id)
            if source is None or not source.is_file():
                raise FileNotFoundError("原始文件不存在")
            result_path = parse_with_mineru(source, document_id)
            document_service.complete_mineru(document_id, result_path)
        elif active_status == DocumentStatus.CHUNKING.value:
            result_path = Path(document["mineru_result_path"]) if document["mineru_result_path"] else None
            if result_path is None or not result_path.is_file():
                raise FileNotFoundError("MinerU Markdown 解析结果不存在")
            chunks_path = create_chunks(result_path, document)
            document_service.complete_chunking(document_id)
            print(f"文档处理完成：{document_id}，切分结果 {chunks_path}", flush=True)
    except Exception as error:
        artifact_dir = settings.parsed_dir / document_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        error_path = artifact_dir / f"{active_status}.error.txt"
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        document_service.fail_processing(document_id, active_status, str(error))
        print(f"文档处理失败：{document_id}，阶段 {active_status}：{error}", flush=True)
    else:
        if active_status == DocumentStatus.MINERU_PARSING.value:
            print(f"MinerU 解析完成：{document_id}", flush=True)
    return True


def run_worker(stop_event: Event) -> None:
    """持续轮询 documents.status；收到停止信号后在当前阶段结束后退出。"""
    print("文档处理 Worker 已启动，等待可处理的文档…", flush=True)
    while not stop_event.is_set():
        try:
            processed = process_next_document()
        except Exception as error:
            print(f"Worker 发生异常：{error}", flush=True)
            processed = False
        if not processed:
            stop_event.wait(max(0.2, settings.worker_poll_interval_seconds))
