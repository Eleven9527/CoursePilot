"""Evaluate retrieval against the current indexed version of the fixture document."""

import argparse
import json
from pathlib import Path

from app.core.config import settings
from app.core.database import connect
from app.rag.vector_store import milvus
from app.services.embedding_service import embed_texts, embedding_collection


def normalize(text: str) -> str:
    return " ".join(text.casefold().replace("’", "'").split())


def load_chunks(filename: str) -> list[dict]:
    with connect() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT chunk.chunk_id,chunk.text FROM document_chunks AS chunk
            JOIN documents AS doc ON doc.id=chunk.document_id AND doc.current_task_id=chunk.task_id
            WHERE doc.filename=? ORDER BY chunk.chunk_index""",
            (filename,),
        ).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--validate-only", action="store_true", help="Check evidence against local chunks")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")

    fixture = json.loads(Path(__file__).with_name("units_1_2.json").read_text(encoding="utf-8"))
    chunks = load_chunks(fixture["source_filename"])
    if not chunks:
        parser.error("The fixture document has no current chunks. Upload and process it first.")

    cases = []
    for case in fixture["cases"]:
        groups = [
            {chunk["chunk_id"] for chunk in chunks
             if all(normalize(phrase) in normalize(chunk["text"]) for phrase in phrases)}
            for phrases in case["evidence"]
        ]
        if any(not group for group in groups):
            parser.error(f"{case['id']}: evidence no longer matches the current chunks; review the fixture.")
        if groups:
            cases.append((case, groups))
        if args.validate_only and groups:
            print(f"{case['id']}: {[sorted(group) for group in groups]}")
    if args.validate_only:
        print(f"Validated {len(cases)} retrieval cases.")
        return 0
    if not settings.embedding_enabled:
        parser.error("Configure Embedding and Milvus in .env first.")

    collection = embedding_collection()
    try:
        if collection not in milvus.list_collections():
            parser.error("The current embedding collection does not exist. Complete document embedding first.")
        vectors = embed_texts([case["question"] for case, _ in cases])
        passed = 0
        for (case, groups), vector in zip(cases, vectors, strict=True):
            hits = milvus.search_vectors(collection, vector, args.top_k)
            retrieved = [str(hit["id"]) for hit in hits]
            matched = sum(bool(group.intersection(retrieved)) for group in groups)
            passed += matched == len(groups)
            print(f"{case['id']}: evidence {matched}/{len(groups)} | hits: {', '.join(retrieved)}")
    except (RuntimeError, ValueError) as exc:
        parser.exit(2, f"Evaluation could not run: {exc}\n")
    print(f"Complete hits@{args.top_k}: {passed}/{len(cases)}")
    print("Q09 and Q10 are reserved for answer evaluation.")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
