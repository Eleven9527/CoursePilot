import json
import re
from pathlib import Path

from app.core.config import settings


def _split_long_text(text: str, limit: int) -> list[str]:
    """优先按句子边界拆分超长段落，必要时再按字符数截开。"""
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[。！？.!?；;])", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _read_sections(markdown: str, limit: int) -> list[tuple[str, str]]:
    """解析 Markdown 标题，并将正文整理为带标题上下文的段落。"""
    headings: list[str] = []
    sections: list[tuple[str, str]] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        paragraph = "\n".join(paragraph_lines).strip()
        paragraph_lines.clear()
        if paragraph:
            sections.append((" / ".join(headings), paragraph))

    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line.strip())
        if match:
            flush_paragraph()
            level = len(match.group(1))
            headings[:] = headings[:level - 1]
            headings.append(match.group(2).strip())
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph_lines.append(line.rstrip())
    flush_paragraph()

    expanded: list[tuple[str, str]] = []
    for heading, paragraph in sections:
        expanded.extend((heading, part) for part in _split_long_text(paragraph, limit))
    return expanded


<<<<<<< HEAD
def create_chunks(markdown_path: Path, document: dict) -> Path:
=======
def create_chunks(markdown_path: Path, document: dict) -> list[dict]:
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
    """按标题和段落边界生成重叠文本块，并以 JSONL 持久化。"""
    chunk_size = settings.chunk_size
    overlap = settings.chunk_overlap
    if chunk_size < 1:
        raise ValueError("CHUNK_SIZE 必须大于 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("CHUNK_OVERLAP 必须大于等于 0 且小于 CHUNK_SIZE")

    markdown = markdown_path.read_text(encoding="utf-8")
    sections = _read_sections(markdown, chunk_size)
    chunks: list[dict] = []
    current_heading = ""
    current_text = ""

    def save_current() -> None:
        nonlocal current_text
        text = current_text.strip()
        if text:
            rendered_text = f"{current_heading}\n\n{text}" if current_heading else text
            chunks.append({
                "chunk_index": len(chunks),
                "text": rendered_text,
                "heading": current_heading,
                "char_count": len(rendered_text),
                "metadata": {
                    "document_id": document["id"],
                    "document_title": document["title"],
                    "grade": document["grade"],
                    "unit": document["unit"],
                    "source_filename": document["filename"],
                    "source_type": document["file_type"],
                },
            })
        current_text = ""

    for heading, paragraph in sections:
        if current_text and heading != current_heading:
            save_current()
        current_heading = heading
        candidate = f"{current_text}\n\n{paragraph}" if current_text else paragraph
        if current_text and len(candidate) > chunk_size:
            previous = current_text
            save_current()
            carry = previous[-overlap:] if overlap else ""
            current_text = f"{carry}\n\n{paragraph}".strip() if carry else paragraph
            if len(current_text) > chunk_size:
                current_text = paragraph
        else:
            current_text = candidate
    save_current()

<<<<<<< HEAD
    output_path = settings.parsed_dir / document["id"] / "chunks.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for chunk in chunks:
            output.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    return output_path
=======
    return chunks
>>>>>>> 710f273831f6f7a5d4460e5895921a05add2da0d
