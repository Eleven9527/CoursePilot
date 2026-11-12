from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from math import log
import re
import unicodedata

from app.core.config import settings
from app.core.database import connect
from app.rag.vector_store import milvus
from app.services.embedding_service import embed_texts, embedding_collection

_UNIT = re.compile(r"第(\d+)(?:-(\d+))?单元")
_QUESTION_NUMBER = re.compile(r"第\s*([1-9]\d*|[一二三四五六七八九十])\s*题")
_CHINESE_NUMBERS = dict(zip("一二三四五六七八九十", range(1, 11)))


def unit_range(label: str) -> tuple[int, int] | None:
    match = _UNIT.fullmatch(label)
    if match:
        first, last = match.groups()
        return int(first), int(last or first)
    return None


def _indexed_documents(grade: str | None = None) -> list[dict]:
    sql = """SELECT doc.id,doc.title,doc.filename,doc.grade,doc.unit,doc.current_task_id
        FROM documents AS doc JOIN parse_task_steps AS step
        ON step.task_id=doc.current_task_id AND step.document_id=doc.id
        WHERE step.step_key='embedding' AND step.status='succeeded'
        AND EXISTS (SELECT 1 FROM document_chunks AS chunk WHERE chunk.task_id=doc.current_task_id)"""
    with connect() as connection:
        rows = connection.execute(sql + (" AND doc.grade=?" if grade else ""), (grade,) if grade else ()).fetchall()
    return [dict(row) for row in rows]


def available_scopes() -> dict[str, list[int]]:
    scopes: dict[str, set[int]] = {}
    for doc in _indexed_documents():
        bounds = unit_range(doc["unit"])
        if bounds and doc["grade"] != "未指定":
            scopes.setdefault(doc["grade"], set()).update(range(bounds[0], bounds[1] + 1))
    return {grade: sorted(units) for grade, units in scopes.items()}


def _tokens(text: str) -> Counter:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    digits = dict(zip("一二三四五六七八九", "123456789"))
    normalized = re.sub(r"第([一二三四五六七八九])题", lambda match: f"第{digits[match[1]]}题", normalized)
    tokens = Counter(re.findall(r"[a-z]+|\d+", normalized))
    for phrase in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return tokens


def _keyword_rank(chunks: dict[str, dict], queries: list[str], limit: int) -> list[str]:
    terms = set().union(*(_tokens(query) for query in queries))
    matches = {key: terms.intersection(_tokens(chunk["text"])) for key, chunk in chunks.items()}
    frequencies = Counter(term for terms_found in matches.values() for term in terms_found)
    scores = {
        key: sum(log(1 + len(chunks) / frequencies[term]) for term in terms_found)
        for key, terms_found in matches.items() if terms_found
    }
    return sorted(scores, key=lambda key: (-scores[key], key))[:limit]


def retrieve(question: str, grade: str, start: int, end: int, top_k: int, rewrite: str = "") -> list[dict]:
    documents = {}
    for doc in _indexed_documents(grade):
        bounds = unit_range(doc["unit"])
        if bounds and bounds[0] <= end and start <= bounds[1]:
            documents[doc["current_task_id"]] = doc
    if not documents:
        return []
    if not settings.embedding_enabled:
        raise RuntimeError("请先配置 Embedding 和 Milvus")

    chunks = {}
    task_ids = list(documents)
    with connect() as connection:
        for offset in range(0, len(task_ids), 500):
            batch = task_ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            for row in connection.execute(
                f"""SELECT chunk_id,task_id,chunk_index,text,heading FROM document_chunks
                WHERE task_id IN ({placeholders})""", batch,
            ).fetchall():
                doc = documents[row["task_id"]]
                chunks[row["chunk_id"]] = {
                    **dict(row), "document_id": doc["id"], "title": doc["title"],
                    "filename": doc["filename"], "grade": doc["grade"], "unit": doc["unit"],
                }
    queries = [question]
    if rewrite and rewrite != question:
        queries.append(rewrite)
    limit = max(20, top_k * 3)
    expression = f"task_id in {json.dumps(task_ids)}"

    def semantic_rank() -> list[list[str]]:
        return [
            [str(hit["id"]) for hit in milvus.search_vectors(
                embedding_collection(), vector, limit, filter_expression=expression,
            ) if str(hit["id"]) in chunks]
            for vector in embed_texts(queries)
        ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        semantic = executor.submit(semantic_rank)
        keywords = executor.submit(_keyword_rank, chunks, queries, limit)
        keyword_results = keywords.result()
        try:
            rankings = [*semantic.result(), keyword_results]
        except RuntimeError as exc:
            if not keyword_results:
                raise
            logging.getLogger(__name__).warning("语义检索暂不可用，使用关键词结果：%s", exc)
            rankings = [keyword_results]
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
    numbered = set()
    match = _QUESTION_NUMBER.search(unicodedata.normalize("NFKC", question))
    if match:
        number = _CHINESE_NUMBERS.get(match[1], match[1])
        heading = re.compile(rf"(?m)^\s*{number}[.、)]\s*\S")
        numbered = {
            chunk_id for chunk_id, chunk in chunks.items()
            if heading.search(unicodedata.normalize("NFKC", chunk["text"]))
        }
    return [
        {**chunks[chunk_id], "score": scores.get(chunk_id, 0.0)}
        for chunk_id in sorted(scores.keys() | numbered,
                               key=lambda key: (key not in numbered, -scores.get(key, 0), key))[:top_k]
    ]
