from pathlib import Path
import re
from uuid import uuid4
from html import escape
<<<<<<< HEAD
import json
import shutil
=======
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from docx import Document as WordDocument

from app.core.config import settings
from app.core.enums import DocumentStatus
from app.schemas.document import DocumentResponse
from app.services import document_service

router = APIRouter(prefix="/documents")
ALLOWED_SUFFIXES = {".pdf", ".md", ".markdown", ".docx"}
ALLOWED_GRADES = {
    "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
    "初一", "初二", "初三", "高一", "高二", "高三", "未指定",
}
ALLOWED_UNITS = {f"第{i}单元" for i in range(1, 21)} | {"未指定"}
MAX_FILE_SIZE = 20 * 1024 * 1024


def _valid_unit(unit: str) -> bool:
    """检查单元或连续单元范围是否在第 1 至第 20 单元内。"""
    if unit in ALLOWED_UNITS:
        return True
    match = re.fullmatch(r"第(\d+)-(\d+)单元", unit)
    if not match:
        return False
    start, end = map(int, match.groups())
    return 1 <= start < end <= 20


async def _save_upload(upload: UploadFile) -> tuple[str, str, str, int]:
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "仅支持 PDF、Markdown 和 DOCX 文件")
    stored_name = f"{uuid4().hex}{suffix}"
    destination = settings.upload_dir / stored_name
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(413, "文件不能超过 20 MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return filename, stored_name, suffix.lstrip("."), size


@router.get("", response_model=list[DocumentResponse])
def list_documents() -> list[dict]:
    return document_service.list_documents()


@router.get("/{document_id}/source")
def get_source_file(document_id: str) -> FileResponse:
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
    path = settings.upload_dir / document["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "原始文件不存在")
    media_types = {
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return FileResponse(
        path,
        media_type=media_types.get(document["file_type"], "application/octet-stream"),
        filename=document["filename"],
        content_disposition_type="inline" if document["file_type"] == "pdf" else "attachment",
    )


@router.get("/{document_id}/source-preview", response_class=HTMLResponse)
def preview_docx(document_id: str) -> HTMLResponse:
    """将 DOCX 的段落和表格渲染成可在浏览器查看的 HTML。"""
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
    if document["file_type"] != "docx":
        raise HTTPException(400, "仅支持预览 DOCX 文件")
    path = settings.upload_dir / document["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "原始文件不存在")

    try:
        word = WordDocument(path)
        blocks: list[str] = []
        for item in word.iter_inner_content():
            if hasattr(item, "rows"):
                rows = []
                for row in item.rows:
                    cells = "".join(f"<td>{escape(cell.text).replace(chr(10), '<br>')}</td>" for cell in row.cells)
                    rows.append(f"<tr>{cells}</tr>")
                blocks.append(f"<table><tbody>{''.join(rows)}</tbody></table>")
            else:
                text = escape(item.text).replace("\n", "<br>")
                if not text:
                    continue
                style = item.style.name if item.style else ""
                if style.startswith("Heading"):
                    level = style.removeprefix("Heading").strip()
                    level = level if level in {"1", "2", "3", "4", "5", "6"} else "2"
                    blocks.append(f"<h{level}>{text}</h{level}>")
                else:
                    blocks.append(f"<p>{text}</p>")
    except Exception as exc:
        raise HTTPException(422, f"DOCX 文件无法预览：{exc}") from exc

    body = "".join(blocks) or "<p>文档中没有可预览的文字内容。</p>"
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{font:15px/1.8 system-ui,'Microsoft YaHei',sans-serif;color:#263445;padding:24px;max-width:900px;margin:auto;white-space:normal}}
p{{margin:0 0 1em}}h1,h2,h3,h4,h5,h6{{line-height:1.4;margin:1.2em 0 .6em}}table{{border-collapse:collapse;width:100%;margin:1em 0}}td{{border:1px solid #cbd5e1;padding:8px;vertical-align:top}}
</style></head><body>{body}</body></html>"""
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline';", "X-Content-Type-Options": "nosniff"})


@router.get("/{document_id}/result")
def get_mineru_result(document_id: str) -> FileResponse:
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
    mineru_result_path = Path(document["mineru_result_path"]) if document["mineru_result_path"] else None
    if mineru_result_path is None or not mineru_result_path.is_file():
        raise HTTPException(409, document["processing_error"] or "解析结果尚未生成")
    return FileResponse(mineru_result_path, media_type="text/markdown; charset=utf-8", filename=mineru_result_path.name)


@router.get("/{document_id}/chunks")
def get_document_chunks(document_id: str) -> JSONResponse:
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
<<<<<<< HEAD
    chunks_path = document_service.get_chunks_path(document_id)
    if chunks_path.is_file():
        with chunks_path.open(encoding="utf-8") as chunks_file:
            chunks = [json.loads(line) for line in chunks_file if line.strip()]
        return JSONResponse({"document_id": document_id, "status": document["status"],
=======
    steps = document_service.get_document_steps(document_id)
    chunk_step = next((step for step in steps if step["step_key"] == ParseStepKey.CHUNKING.value), None)
    chunks = document_service.read_chunking_result(chunk_step)
    if chunks is not None:
        return JSONResponse({"document_id": document_id, "status": ParseStepStatus.SUCCEEDED.value,
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
                             "chunk_count": len(chunks), "chunks": chunks})
    return JSONResponse({
        "document_id": document_id,
        "status": document["status"],
        "error": document["processing_error"],
        "chunk_count": 0,
        "chunks": [],
    }, status_code=202)


@router.post("/{document_id}/chunks")
def generate_document_chunks(document_id: str) -> JSONResponse:
    """将文档当前状态推进到已有 MinerU 结果后的切分阶段。"""
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
<<<<<<< HEAD
    mineru_result_path = Path(document["mineru_result_path"]) if document["mineru_result_path"] else None
    if mineru_result_path is None or not mineru_result_path.is_file():
        raise HTTPException(409, "Markdown 解析结果尚未生成，无法切分")
    chunks_path = document_service.get_chunks_path(document_id)
    if document["status"] == DocumentStatus.SUCCEEDED.value and chunks_path.is_file():
        with chunks_path.open(encoding="utf-8") as chunks_file:
            chunks = [json.loads(line) for line in chunks_file if line.strip()]
        return JSONResponse({"document_id": document_id, "status": DocumentStatus.SUCCEEDED.value,
                             "chunk_count": len(chunks), "chunks": chunks})
    if not document_service.queue_chunking(document_id):
        raise HTTPException(409, "文档当前状态不能进入文本切分")
    return JSONResponse({"document_id": document_id, "status": DocumentStatus.MINERU_PARSED.value,
                         "chunk_count": 0, "chunks": []}, status_code=status.HTTP_202_ACCEPTED)


=======
    task_id = document["current_task_id"]
    if not task_id:
        raise HTTPException(409, "文档没有可关联的解析任务")

    steps = document_service.get_document_steps(document_id)
    chunk_step = next((step for step in steps if step["step_key"] == ParseStepKey.CHUNKING.value), None)
    chunks = document_service.read_chunking_result(chunk_step)
    if chunks is not None:
        return JSONResponse({"document_id": document_id, "status": ParseStepStatus.SUCCEEDED.value,
                             "chunk_count": len(chunks), "chunks": chunks})
    parsed_path = Path(document["parsed_path"]) if document["parsed_path"] else None
    if parsed_path is None or not parsed_path.is_file():
        raise HTTPException(409, "Markdown 解析结果尚未生成，无法切分")
    try:
        queued_status = document_service.queue_chunking_step(task_id, document_id, parsed_path)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse({"document_id": document_id, "status": queued_status,
                         "chunk_count": 0, "chunks": []}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/{document_id}/embedding/retry", status_code=202)
def retry_document_embedding(document_id: str) -> dict[str, str]:
    if document_service.get_document(document_id) is None:
        raise HTTPException(404, "文档不存在")
    if not settings.embedding_enabled:
        raise HTTPException(409, "请先配置 Embedding 和 Milvus")
    if not document_service.retry_embedding(document_id):
        raise HTTPException(409, "当前任务没有失败的向量化步骤")
    return {"status": ParseStepStatus.QUEUED.value}


@router.get("/{document_id}/steps", response_model=list[ParseStepResponse])
def get_parse_steps(document_id: str) -> list[dict]:
    if document_service.get_document(document_id) is None:
        raise HTTPException(404, "文档不存在")
    result = []
    for step in document_service.get_document_steps(document_id):
        artifact_url = None
        if step["step_key"] == ParseStepKey.SOURCE_SAVED.value:
            artifact_url = f"{settings.api_prefix}/documents/{document_id}/source"
        elif step["step_key"] == ParseStepKey.CHUNKING.value and step["status"] == ParseStepStatus.SUCCEEDED.value:
            artifact_url = f"{settings.api_prefix}/documents/{document_id}/chunks"
        elif step["output_path"] and Path(step["output_path"]).is_file():
            artifact = "chunks" if step["step_key"] == "chunking" else "result"
            artifact_url = f"{settings.api_prefix}/documents/{document_id}/{artifact}"
        result.append({**step, "artifact_url": artifact_url})
    return result


>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    grade: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
) -> dict:
    if grade not in ALLOWED_GRADES:
        raise HTTPException(400, "请选择有效的年级")
    if not _valid_unit(unit):
        raise HTTPException(400, "请选择有效的单元")
    document_id = uuid4().hex
    filename, stored_name, file_type, size_bytes = await _save_upload(file)
    resolved_title = title.strip() or Path(filename).stem
    document = document_service.create_document(
        document_id, resolved_title, grade, unit, description.strip(), filename,
        stored_name, file_type, size_bytes,
    )
    return document


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    title: str = Form(...),
    grade: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict:
    existing = document_service.get_document(document_id)
    if existing is None:
        raise HTTPException(404, "文档不存在")
    if grade not in ALLOWED_GRADES:
        raise HTTPException(400, "请选择有效的年级")
    if not _valid_unit(unit):
        raise HTTPException(400, "请选择有效的单元")
    replacement = await _save_upload(file) if file and file.filename else None
    new_record = document_service.update_document(
        document_id, title.strip(), grade, unit, description.strip(), replacement
    )
    if replacement:
        old_path = settings.upload_dir / existing["stored_name"]
        old_path.unlink(missing_ok=True)
    if new_record is None:
        raise HTTPException(404, "文档不存在")
    return new_record


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    paths = document_service.delete_document(document_id)
    if paths is None:
        raise HTTPException(404, "文档不存在")
    source_path, mineru_result_path = paths
    source_path.unlink(missing_ok=True)
    if mineru_result_path:
        mineru_result_path.unlink(missing_ok=True)


@router.post("/{document_id}/process", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_processing(document_id: str) -> dict:
    if not document_service.queue_processing(document_id):
        if document_service.get_document(document_id) is None:
            raise HTTPException(404, "文档不存在")
        raise HTTPException(409, "文档正在处理中")
<<<<<<< HEAD
    document = document_service.get_document(document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
    return document
=======
    task = document_service.get_task(task_id)
    if task is None:
        raise HTTPException(500, "解析任务已创建，但无法读取任务记录")
    return task


@router.get("/tasks/{task_id}", response_model=ParseTaskResponse)
def get_parse_task(task_id: str) -> dict:
    task = document_service.get_task(task_id)
    if task is None:
        raise HTTPException(404, "解析任务不存在")
    return task
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
