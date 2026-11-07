"""Milvus REST client for embeddings produced by the ingestion pipeline."""

import json
from urllib.request import Request, urlopen

from app.core.config import settings


def _request(action: str, payload: dict) -> dict | list:
    if not settings.milvus_uri:
        raise RuntimeError("请先设置 MILVUS_URI")
    headers = {"Content-Type": "application/json"}
    if settings.milvus_token:
        headers["Authorization"] = f"Bearer {settings.milvus_token}"
    request = Request(
        f"{settings.milvus_uri.rstrip('/')}/v2/vectordb/{action}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Milvus 请求失败 ({action}): {exc}") from exc
    if result.get("code") != 0:
        raise RuntimeError(f"Milvus 请求失败 ({action}): {result.get('message', result.get('code'))}")
    return result.get("data", {})


def list_collections() -> list[str]:
    return _request("collections/list", {})


def create_collection(name: str, dimension: int) -> None:
    _request("collections/create", {
        "collectionName": name,
        "schema": {
            "autoId": False,
            "enableDynamicField": True,
            "fields": [
                {"fieldName": "id", "dataType": "VarChar", "isPrimary": True,
                 "elementTypeParams": {"max_length": "128"}},
                {"fieldName": "vector", "dataType": "FloatVector",
                 "elementTypeParams": {"dim": str(dimension)}},
            ],
        },
        "indexParams": [
            {"fieldName": "vector", "indexName": "vector_cosine",
             "metricType": "COSINE", "params": {"index_type": "AUTOINDEX"}},
        ],
    })


def upsert_vectors(collection: str, rows: list[dict]) -> None:
    """Rows contain a stable string id, a vector, and optional metadata."""
    if rows:
        _request("entities/upsert", {"collectionName": collection, "data": rows})


def search_vectors(collection: str, vector: list[float], limit: int = 10) -> list[dict]:
    return _request("entities/search", {
        "collectionName": collection,
        "data": [vector],
        "annsField": "vector",
        "limit": limit,
    })
