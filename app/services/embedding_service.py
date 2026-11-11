import hashlib
import json
from math import isfinite
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.core.config import settings
from app.rag.vector_store import milvus


def embed_texts(texts: list[str]) -> list[list[float]]:
    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"
    request = Request(
        f"{settings.embedding_base_url.rstrip('/')}/embeddings",
        data=json.dumps({"model": settings.embedding_model, "input": texts}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Embedding 服务返回 HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("Embedding 请求失败或响应格式无效") from exc

    vectors = {}
    for item in payload["data"]:
        index, vector = item["index"], item["embedding"]
        if (type(index) is not int or index in vectors or not isinstance(vector, list)
                or len(vector) != settings.embedding_dimension
                or any(type(value) not in (int, float) or not isfinite(value) for value in vector)):
            raise ValueError("Embedding 响应的索引、维度或向量值无效")
        vectors[index] = vector
    if vectors.keys() != set(range(len(texts))):
        raise ValueError("Embedding 返回的向量数量或索引与请求不一致")
    return [vectors[index] for index in range(len(texts))]


def embedding_collection() -> str:
    model_key = f"{settings.embedding_base_url.rstrip('/')}:{settings.embedding_model}:{settings.embedding_dimension}"
    return f"coursepilot_chunks_{hashlib.sha256(model_key.encode()).hexdigest()[:16]}"


def embed_chunks(chunks: list[dict], document_id: str, task_id: str) -> int:
    if not chunks:
        return 0
    collection = embedding_collection()
    if collection not in milvus.list_collections():
        milvus.create_collection(collection, settings.embedding_dimension)
    for offset in range(0, len(chunks), 16):
        batch = chunks[offset:offset + 16]
        vectors = embed_texts([chunk["text"] for chunk in batch])
        milvus.upsert_vectors(collection, [
            {"id": chunk["chunk_id"], "vector": vector, "document_id": document_id, "task_id": task_id}
            for chunk, vector in zip(batch, vectors, strict=True)
        ])
    return len(chunks)
